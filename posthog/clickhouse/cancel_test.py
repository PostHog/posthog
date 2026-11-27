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
    kills: list[tuple[str, str, dict[str, Any]]] = []

    @contextmanager
    def connect(*, host: str, **_kwargs: object) -> "Iterator[str]":
        if legacy_unavailable and host == "legacy.example.com":
            raise ConnectionError("Legacy cluster unavailable")
        yield host

    def execute(query: str, params: dict[str, Any], *, sync_client: str) -> list[list[str]]:
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
        assert kills[0][1] == "KILL QUERY WHERE query_id IN %(query_ids)s ASYNC SETTINGS max_execution_time = 5"
        assert kills[0][2] == {"query_ids": ["42_requested_suffix"]}
    else:
        for host, query, params in kills:
            cluster = "legacy" if host == "legacy.example.com" else "events"
            assert "KILL QUERY ON CLUSTER %(cluster)s" in query
            assert "startsWith(query_id, %(client_query_id)s)" in query
            assert params == {"cluster": cluster, "client_query_id": "42_requested"}


def _running(tag: str) -> int:
    return sync_execute("SELECT count() FROM system.processes WHERE position(query_id, %(tag)s) > 0", {"tag": tag})[0][
        0
    ]


def _start_slow_query(team_id: int, client_query_id: str, errors: list[Exception]) -> Thread:
    def run_slow_query() -> None:
        with tags_context(team_id=team_id, client_query_id=client_query_id):
            try:
                sync_execute("SELECT sleepEachRow(0.2) FROM numbers(150) SETTINGS max_block_size = 1")
            except Exception as error:
                errors.append(error)

    thread = Thread(target=run_slow_query)
    thread.start()
    return thread


# The node reports a host name that the test process cannot always resolve, so the kill goes to the test host.
def _connect_to_the_test_host(*, host: str, **kwargs: Any) -> Any:
    return default_client(host=settings.CLICKHOUSE_HOST, **kwargs)


@pytest.mark.django_db
def test_cancels_all_series_and_the_build_for_one_request() -> None:
    team_id = 42
    requester_query_id = f"anomaly_scoring_{uuid4().hex}"
    errors: list[Exception] = []
    ids = [requester_query_id, requester_query_id, f"{uuid4()}_{requester_query_id}"]
    threads = [_start_slow_query(team_id, query_id, errors) for query_id in ids]
    try:
        wait_until(lambda: _running(requester_query_id) == 3, timeout=15, message="the slow queries did not start")
        with (
            tags_context(team_id=team_id, client_query_id=requester_query_id),
            patch("posthog.clickhouse.cancel.default_client", side_effect=_connect_to_the_test_host),
        ):
            cancel_queries_started_for(team_id, requester_query_id)
    finally:
        for thread in threads:
            thread.join(timeout=40)

    assert not any(thread.is_alive() for thread in threads)
    assert [type(error) for error in errors] == [CHQueryErrorQueryWasCancelled] * 3


def test_a_failed_host_does_not_stop_the_batch_for_the_next_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CLICKHOUSE_EVENTS_ONLINE_HOST", None)
    monkeypatch.setattr(settings, "CLICKHOUSE_EVENTS_OFFLINE_HOST", None)
    killed: list[tuple[str, list[str]]] = []

    def execute(query: str, params: dict[str, Any], *, sync_client: str) -> list:
        if query.lstrip().startswith("SELECT"):
            return [("down", "a"), ("up", "b"), ("up", "c"), ("up", "b")]
        if sync_client == "down":
            raise ConnectionError("host unreachable")
        killed.append((sync_client, params["query_ids"]))
        return []

    with (
        patch("posthog.clickhouse.cancel.default_client", side_effect=lambda **kwargs: nullcontext(kwargs["host"])),
        patch("posthog.clickhouse.cancel.sync_execute", side_effect=execute),
    ):
        cancel_queries_started_for(42, "request")

    assert killed == [("up", ["b", "c"])]


@pytest.mark.parametrize("fallback", [False, True])
def test_a_group_fallback_uses_the_same_match_as_discovery(fallback: bool) -> None:
    with (
        patch("posthog.clickhouse.cancel._lookup_hosts", return_value={"legacy": "lookup"}),
        patch("posthog.clickhouse.cancel.default_client", return_value=nullcontext("lookup")),
        patch("posthog.clickhouse.cancel.sync_execute", return_value=[]) as execute,
    ):
        cancel_queries_started_for(42, "attempt:1", fallback_on_cluster=fallback)

    lookup, *kills = execute.call_args_list
    assert len(kills) == int(fallback)
    if fallback:
        (kill,) = kills
        predicate = "match(query_id, concat(%(start)s, regexpQuoteMeta(%(client_query_id)s), %(end)s))"
        assert predicate in lookup.args[0] and predicate in kill.args[0]
        assert "KILL QUERY ON CLUSTER" in kill.args[0]
        assert kill.args[1] == lookup.args[1]


@pytest.mark.django_db
def test_a_query_whose_own_id_only_contains_the_id_is_left_running() -> None:
    team_id = 42
    requester_query_id = f"alert-check:{uuid4()}"
    other_query_id = f"mydata_{requester_query_id}"
    errors: list[Exception] = []

    thread = _start_slow_query(team_id, other_query_id, errors)
    try:
        wait_until(lambda: _running(other_query_id) == 1, timeout=15, message="the slow query did not start")
        with patch("posthog.clickhouse.cancel.default_client", side_effect=_connect_to_the_test_host):
            cancel_queries_started_for(team_id, requester_query_id)
            still_running = _running(other_query_id)
            cancel_queries_started_for(team_id, other_query_id)
    finally:
        thread.join(timeout=40)

    assert still_running == 1
    assert not thread.is_alive()
