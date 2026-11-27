from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING

import pytest
from unittest.mock import patch

from posthog.schema import HogQLQueryModifiers

from posthog import settings
from posthog.clickhouse.cancel import cancel_query_on_cluster
from posthog.models.event.new_events_schema import events_route_scope

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
