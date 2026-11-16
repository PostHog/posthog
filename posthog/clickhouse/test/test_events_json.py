import json
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import EVENTS_JSON_INSERT_SETTINGS, is_temporary_event_property


@pytest.mark.parametrize(
    "key, expected",
    [
        ("$set", True),
        ("$lib_custom_api_host", True),
        ("$sdk_debug_replay_flushed_size", True),
        ("$sdk_debug_current_session_duration.value", True),
        ("$set.foo", False),
        ("$sent_at", False),
        ("$sdk_debug_current_session_duration", False),
        ("custom", False),
    ],
)
def test_is_temporary_event_property(key: str, expected: bool) -> None:
    assert is_temporary_event_property(key) is expected


class TestEventsJsonRecent(ClickhouseTestMixin, BaseTest):
    def test_stores_the_text_batch_exports_read_from_events_json(self) -> None:
        event_uuid = uuid4()
        properties = {
            "$browser": "Chrome",
            "$current_url": "https://example.com/a/b?x=1",
            "$feature_flags": {"flag-a": True, "flag-b": "variant"},
            "$set": {"email": "a@example.com"},
            "a.b": 1,
            "nested": {"x.y": [1, 2.5, "s"]},
            "text": 'héllo 🦔 "quoted" /x/y/',
        }
        person_properties = {"email": "a@example.com", "$browser": "Firefox"}

        # The cleaner is an executable UDF that a VALUES insert can't call, so the row goes through a SELECT.
        sync_execute(
            f"""
            INSERT INTO writable_events_json (
                uuid, event, properties, temporary_properties, properties_null_keys, temporary_properties_null_keys,
                timestamp, team_id, distinct_id, elements_chain, person_id, person_properties,
                person_properties_null_keys, _timestamp, _offset
            )
            SELECT
                %(uuid)s, '$pageview', cleaned.properties, cleaned.temporary_properties, cleaned.properties_null_keys,
                cleaned.temporary_properties_null_keys, now64(), %(team_id)s, 'distinct-id', '', %(uuid)s,
                cleaned.person_properties, cleaned.person_properties_null_keys, now(), 0
            FROM (SELECT JSONCleanPostHogEvent(%(properties)s, %(person_properties)s) AS cleaned)
            SETTINGS distributed_foreground_insert = 1, {EVENTS_JSON_INSERT_SETTINGS}
            """,
            {
                "uuid": event_uuid,
                "team_id": self.team.pk,
                "properties": json.dumps(properties),
                "person_properties": json.dumps(person_properties),
            },
        )

        [(recent, from_events_json)] = sync_execute(
            """
            SELECT
                (r.properties, r.person_properties, r.temporary_properties, r.inserted_at),
                (toJSONString(e.properties), toJSONString(e.person_properties), toJSONString(e.temporary_properties), e.inserted_at)
            FROM events_json_recent AS r
            JOIN events_json AS e ON e.uuid = r.uuid
            WHERE r.team_id = %(team_id)s AND e.team_id = %(team_id)s AND r.uuid = %(uuid)s
            SETTINGS json_type_escape_dots_in_keys = 1, output_format_json_escape_forward_slashes = 0
            """,
            {"uuid": event_uuid, "team_id": self.team.pk},
        )

        assert recent == from_events_json
