import json
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.hogql.printer.events_json_document import (
    EVENTS_PROPERTIES_DECLARED_STRING_PATHS,
    json_document_sql,
    person_document_sql,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import is_temporary_event_property
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
    def test_stores_export_documents_with_temporary_properties_and_keeps_flag_calls(self) -> None:
        # Both MVs read Kafka tables. A Null table with the Kafka columns, virtual ones included with Kafka's types,
        # lets one insert feed both of them.
        source = "test_events_json_recent_source"
        sync_execute(
            EVENTS_TABLE_BASE_SQL.format(
                table_name=source,
                on_cluster_clause="",
                engine="Null",
                extra_fields=KAFKA_EVENTS_NATIVE_JSON_EXTRA_FIELDS
                + ", _timestamp Nullable(DateTime), _offset UInt64, _partition UInt64"
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
            "key/with/slashes": "v",
        }
        person_properties = {"email": "a@example.com", "$browser": "Firefox"}
        sync_execute(
            f"""
            INSERT INTO {source} (uuid, event, properties, person_properties, timestamp, team_id, distinct_id, _timestamp)
            VALUES
                (%(pageview_uuid)s, '$pageview', %(properties)s, %(person_properties)s, now64(), %(team_id)s, 'd1', now()),
                (%(flag_call_uuid)s, '$feature_flag_called', '{{}}', '{{}}', now64(), %(team_id)s, 'd1', now())
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
            ORDER BY event
            """,
            uuids,
        )
        from_events_json = sync_execute(
            f"""
            SELECT
                uuid,
                {json_document_sql("properties", exclude_empty_key="$feature_flags", declared_string_paths=EVENTS_PROPERTIES_DECLARED_STRING_PATHS)},
                {person_document_sql("person_properties")},
                {json_document_sql("temporary_properties")}
            FROM events_json
            WHERE team_id = %(team_id)s AND uuid IN %(uuids)s
            ORDER BY event
            SETTINGS json_type_escape_dots_in_keys = 1
            """,
            uuids,
        )

        assert [row[0] for row in recent] == [flag_call_uuid, pageview_uuid]
        # events_json keeps the temporary properties in their own column. The recent table also has them in properties.
        assert [(row[0], *(json.loads(document) for document in row[1:])) for row in recent] == [
            (uuid, {**json.loads(stored), **json.loads(temporary)}, json.loads(person), json.loads(temporary))
            for uuid, stored, person, temporary in from_events_json
        ]
        _, stored_properties, stored_person_properties, stored_temporary_properties = recent[1]
        assert {
            "properties": json.loads(stored_properties),
            "person_properties": json.loads(stored_person_properties),
            "temporary_properties": json.loads(stored_temporary_properties),
        } == {
            "properties": {
                "$browser": "Chrome",
                "$current_url": "https://example.com/a/b?x=1",
                "$feature_flags": {"flag-a": "true", "flag-b": "variant"},
                "$set": {"email": "a@example.com"},
                "a.b": 1,
                "nested": {"x.y": [1, 2.5, "s"]},
                "text": 'héllo 🦔 "quoted" /x/y/',
                "key/with/slashes": "v",
            },
            "person_properties": person_properties,
            "temporary_properties": {"$set": {"email": "a@example.com"}},
        }
