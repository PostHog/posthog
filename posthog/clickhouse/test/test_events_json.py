import json
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import is_temporary_event_property
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS_WITH_PARTITION
from posthog.models.event.sql import (
    EVENTS_JSON_RECENT_MV_SQL,
    EVENTS_JSON_TABLE_MV_SQL,
    EVENTS_TABLE_BASE_SQL,
    KAFKA_EVENTS_NATIVE_JSON_EXTRA_FIELDS,
)


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
    def test_stores_the_text_batch_exports_read_from_events_json_without_flag_calls(self) -> None:
        # Both MVs read Kafka tables. A Null table with the Kafka columns lets one insert feed both of them.
        source = "test_events_json_recent_source"
        sync_execute(
            EVENTS_TABLE_BASE_SQL.format(
                table_name=source,
                on_cluster_clause="",
                engine="Null",
                extra_fields=KAFKA_EVENTS_NATIVE_JSON_EXTRA_FIELDS
                + KAFKA_COLUMNS_WITH_PARTITION
                + ", `_headers.name` Array(String), `_headers.value` Array(String)",
                dynamically_materialized_columns="",
                materialized_columns="",
                indexes="",
            )
        )
        self.addCleanup(sync_execute, f"DROP TABLE IF EXISTS {source}")
        sync_execute(EVENTS_JSON_TABLE_MV_SQL(mv_name=f"{source}_events_json_mv", kafka_table=source, on_cluster=False))
        self.addCleanup(sync_execute, f"DROP TABLE IF EXISTS {source}_events_json_mv")
        sync_execute(EVENTS_JSON_RECENT_MV_SQL(mv_name=f"{source}_recent_mv", kafka_table=source))
        self.addCleanup(sync_execute, f"DROP TABLE IF EXISTS {source}_recent_mv")

        pageview_uuid, flag_call_uuid = uuid4(), uuid4()
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
        sync_execute(
            f"""
            INSERT INTO {source} (uuid, event, properties, person_properties, timestamp, team_id, distinct_id)
            VALUES
                (%(pageview_uuid)s, '$pageview', %(properties)s, %(person_properties)s, now64(), %(team_id)s, 'd1'),
                (%(flag_call_uuid)s, '$feature_flag_called', '{{}}', '{{}}', now64(), %(team_id)s, 'd1')
            """,
            {
                "pageview_uuid": pageview_uuid,
                "flag_call_uuid": flag_call_uuid,
                "team_id": self.team.pk,
                "properties": json.dumps(properties),
                "person_properties": json.dumps(person_properties),
            },
        )

        uuids = {"team_id": self.team.pk, "uuids": [pageview_uuid, flag_call_uuid]}
        recent = sync_execute(
            """
            SELECT uuid, properties, person_properties, temporary_properties
            FROM events_json_recent
            WHERE team_id = %(team_id)s AND uuid IN %(uuids)s
            """,
            uuids,
        )
        from_events_json = sync_execute(
            """
            SELECT uuid, toJSONString(properties), toJSONString(person_properties), toJSONString(temporary_properties)
            FROM events_json
            WHERE team_id = %(team_id)s AND uuid IN %(uuids)s AND event != '$feature_flag_called'
            SETTINGS json_type_escape_dots_in_keys = 1, output_format_json_escape_forward_slashes = 0
            """,
            uuids,
        )

        assert [row[0] for row in from_events_json] == [pageview_uuid]
        assert recent == from_events_json
