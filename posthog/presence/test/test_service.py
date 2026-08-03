from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

import redis.exceptions as redis_exceptions
from parameterized import parameterized

from posthog.presence import service

TEAM_ID = 1
SCOPE = "conversations_ticket"
ITEM_ID = "ticket-1"
NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_keys():
    from posthog import redis as redis_module

    client = redis_module.get_client()
    for key in service._keys(TEAM_ID, SCOPE, ITEM_ID):
        client.delete(key)
    yield


def _beat(client_id: str, *, user_id: int = 1, activity: service.PresenceActivity = "viewing", at: datetime = NOW):
    return service.heartbeat(TEAM_ID, SCOPE, ITEM_ID, client_id=client_id, user_id=user_id, activity=activity, now=at)


def test_stale_viewers_are_evicted_and_their_payload_cleaned_up():
    from posthog import redis as redis_module

    _beat("old-tab", user_id=1)
    later = NOW + timedelta(seconds=service.PRESENCE_TTL_SECONDS + 1)
    entries = _beat("new-tab", user_id=2, at=later)

    assert [entry.client_id for entry in entries] == ["new-tab"]
    # The payload has to go too, or an item accumulates hash fields for every tab that ever opened it.
    index_key, meta_key = service._keys(TEAM_ID, SCOPE, ITEM_ID)
    client = redis_module.get_client()
    assert client.hkeys(meta_key) == [b"new-tab"]
    assert client.zscore(index_key, "old-tab") is None


def test_repeat_heartbeat_from_same_client_replaces_rather_than_duplicates():
    _beat("tab", user_id=7)
    _beat("tab", user_id=7, activity="composing", at=NOW + timedelta(seconds=1))
    entries = _beat("tab", user_id=7, at=NOW + timedelta(seconds=2))

    assert len(entries) == 1
    assert entries[0].activity == "viewing"


@parameterized.expand(
    [
        ("just_inside", service.COMPOSING_TTL_SECONDS - 1, "composing"),
        ("just_outside", service.COMPOSING_TTL_SECONDS + 1, "viewing"),
    ]
)
def test_composing_decays_to_viewing(_name: str, age_seconds: int, expected: str):
    _beat("tab", activity="composing")

    entries = service.get_viewers(TEAM_ID, SCOPE, ITEM_ID, now=NOW + timedelta(seconds=age_seconds))

    assert [entry.activity for entry in entries] == [expected]


@parameterized.expand([("heartbeat",), ("get_viewers",), ("leave",)])
def test_redis_errors_degrade_to_nobody_present(operation: str):
    with patch("posthog.redis.get_client", side_effect=redis_exceptions.ConnectionError("down")):
        if operation == "heartbeat":
            assert _beat("tab") == []
        elif operation == "get_viewers":
            assert service.get_viewers(TEAM_ID, SCOPE, ITEM_ID, now=NOW) == []
        else:
            service.leave(TEAM_ID, SCOPE, ITEM_ID, client_id="tab")


def test_presence_is_isolated_per_item():
    _beat("tab")

    assert service.get_viewers(TEAM_ID, SCOPE, "other-ticket", now=NOW) == []
    assert service.get_viewers(TEAM_ID + 1, SCOPE, ITEM_ID, now=NOW) == []
