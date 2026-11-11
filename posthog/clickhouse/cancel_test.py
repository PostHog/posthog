from contextlib import contextmanager
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
    "events_online,events_offline,running_cluster,expected_kill_hosts",
    [
        (None, None, "legacy", ["initiator.example.com"]),
        ("events.example.com", None, "legacy", ["initiator.example.com"]),
        ("events.example.com", None, "events", ["initiator.example.com"]),
        (None, "events-offline.example.com", "events", ["initiator.example.com"]),
        (None, None, None, ["legacy.example.com"]),
        ("events.example.com", None, None, ["legacy.example.com", "events.example.com"]),
    ],
)
def test_cancellation_finds_the_query_regardless_of_the_current_schema(
    monkeypatch: pytest.MonkeyPatch,
    events_online: str | None,
    events_offline: str | None,
    running_cluster: str | None,
    expected_kill_hosts: list[str],
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
        yield host

    def execute(query: str, params: dict[str, str], *, sync_client: str) -> list[list[str]]:
        if query.lstrip().startswith("SELECT"):
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
    ):
        cancel_query_on_cluster(42, "requested")

    assert [host for host, _query, _params in kills] == expected_kill_hosts
    if running_cluster:
        assert kills[0][1] == "KILL QUERY WHERE query_id=%(query_id)s SETTINGS max_execution_time = 5"
        assert kills[0][2] == {"query_id": "42_requested_suffix"}
    else:
        assert "KILL QUERY ON CLUSTER 'legacy'" in kills[0][1]
        if events_online:
            assert "KILL QUERY ON CLUSTER 'events'" in kills[1][1]
        assert all(params == {"client_query_id": "42_requested%"} for _host, _query, params in kills)
