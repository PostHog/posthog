from contextlib import contextmanager, nullcontext
from threading import Thread
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from unittest.mock import patch

from posthog.schema import HogQLQueryModifiers

from posthog import settings
from posthog.clickhouse.cancel import cancel_queries_started_for, cancel_query_on_cluster
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import default_client
from posthog.clickhouse.query_tagging import tags_context
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.models.event.new_events_schema import events_route_scope
from posthog.test.waiting import wait_until

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.mark.parametrize(
    "events_online,events_offline,running_cluster,expected_kill_hosts,legacy_unavailable",
    [
        (None, None, "legacy", ["initiator.example.com"], False),
        ("events.example.com", None, "legacy", ["initiator.example.com"], False),
        ("events.example.com", None, "events", ["initiator.example.com"], False),
        (None, "events-offline.example.com", "events", ["initiator.example.com"], False),
        (None, None, None, ["legacy.example.com"], False),
        ("events.example.com", None, None, ["legacy.example.com", "events.example.com"], False),
        ("events.example.com", None, None, ["events.example.com"], True),
        (None, None, None, [], True),
    ],
)
def test_cancellation_finds_the_query_regardless_of_the_current_schema(
    monkeypatch: pytest.MonkeyPatch,
    events_online: str | None,
    events_offline: str | None,
    running_cluster: str | None,
    expected_kill_hosts: list[str],
    legacy_unavailable: bool,
) -> None:
    monkeypatch.setattr(settings, "CLICKHOUSE_HOST", "legacy.example.com")
    monkeypatch.setattr(settings, "CLICKHOUSE_CLUSTER", "legacy")
    monkeypatch.setattr(settings, "CLICKHOUSE_EVENTS_CLUSTER", "events")
    monkeypatch.setattr(settings, "CLICKHOUSE_EVENTS_ONLINE_HOST", events_online)
    monkeypatch.setattr(settings, "CLICKHOUSE_EVENTS_OFFLINE_HOST", events_offline)
    monkeypatch.setattr(settings, "CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER", True)
    kills: list[tuple[str, str, dict[str, str]]] = []

    @contextmanager
    def connect(*, host: str, **_kwargs: object) -> "Iterator[str]":
        if legacy_unavailable and host == "legacy.example.com":
            raise ConnectionError("Legacy cluster unavailable")
        yield host

    def execute(query: str, params: dict[str, str], *, sync_client: str) -> list[list[str]]:
        if query.lstrip().startswith("SELECT"):
            assert "startsWith(query_id, %(client_query_id)s)" in query
            assert params["client_query_id"] == "42_requested"
            expected_host = "legacy.example.com" if params["cluster"] == "legacy" else events_online or events_offline
            assert sync_client == expected_host
            if params["cluster"] == running_cluster:
                return [["initiator.example.com", "42_requested_suffix"]]
            return []
        kills.append((sync_client, query, params))
        return []

    with (
        events_route_scope(HogQLQueryModifiers(useNewEventsSchema=running_cluster != "events")),
        patch("posthog.clickhouse.cancel.default_client", side_effect=connect),
        patch("posthog.clickhouse.cancel.sync_execute", side_effect=execute),
        pytest.raises(ConnectionError) if legacy_unavailable else nullcontext(),
    ):
        cancel_query_on_cluster(42, "requested")

    assert [host for host, _query, _params in kills] == expected_kill_hosts
    if running_cluster:
        assert kills[0][1] == "KILL QUERY WHERE query_id=%(query_id)s SETTINGS max_execution_time = 5"
        assert kills[0][2] == {"query_id": "42_requested_suffix"}
    else:
        for host, query, params in kills:
            cluster = "legacy" if host == "legacy.example.com" else "events"
            assert f"KILL QUERY ON CLUSTER '{cluster}'" in query
            assert "startsWith(query_id, %(client_query_id)s)" in query
            assert params == {"client_query_id": "42_requested"}


def _is_running(tag: str) -> bool:
    return bool(
        sync_execute("SELECT count() FROM system.processes WHERE position(query_id, %(tag)s) > 0", {"tag": tag})[0][0]
    )


@pytest.mark.django_db
def test_stops_a_running_query_that_carries_the_id_of_the_query_it_was_started_for() -> None:
    team_id = 42
    requester_query_id = f"alert-check:{uuid4()}"
    errors: list[Exception] = []

    def run_slow_query() -> None:
        with tags_context(team_id=team_id, client_query_id=f"{uuid4()}_{requester_query_id}"):
            try:
                sync_execute("SELECT sleepEachRow(0.2) FROM numbers(150) SETTINGS max_block_size = 1")
            except Exception as error:
                errors.append(error)

    # The node reports a host name that the test process cannot always resolve, so the kill goes to the test host.
    def connect_to_the_test_host(*, host: str, **kwargs: Any) -> Any:
        return default_client(host=settings.CLICKHOUSE_HOST, **kwargs)

    thread = Thread(target=run_slow_query)
    thread.start()
    try:
        wait_until(lambda: _is_running(requester_query_id), timeout=15, message="the slow query did not start")
        with patch("posthog.clickhouse.cancel.default_client", side_effect=connect_to_the_test_host):
            cancel_queries_started_for(team_id, requester_query_id)
    finally:
        thread.join(timeout=40)

    assert not thread.is_alive()
    [error] = errors
    assert isinstance(error, CHQueryErrorQueryWasCancelled)
