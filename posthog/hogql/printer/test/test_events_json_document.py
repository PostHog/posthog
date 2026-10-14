import json

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.printer.events_json_document import event_document_sql, person_document_sql

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import TEMPORARY_PROPERTIES_JSON_TYPE
from posthog.models.event.sql import EVENTS_PROPERTIES_JSON_TYPE, PERSON_PROPERTIES_JSON_TYPE

# A sent empty value under a dynamic key stays; the declared paths read '' or [] whether sent empty or absent,
# so the document leaves those out.
EVENT_DOCUMENTS = [
    ({"$browser": "Chrome", "pathname": "/docs", "empty": "", "list": [], "nested": {"child": ""}}, None),
    ({"$browser": "", "$exception_types": [], "custom_list": [], "note": ""}, {"custom_list": [], "note": ""}),
    ({}, None),
]
PERSON_DOCUMENTS = [
    ({"$initial_browser": "Chrome", "email": "a@example.com", "empty": "", "list": []}, None),
    ({"$initial_browser": "", "$browser": "", "list": [], "note": ""}, {"list": [], "note": ""}),
    ({}, None),
]


@pytest.mark.usefixtures("clickhouse_database")
class TestEventsJsonDocument(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "event",
                "properties",
                event_document_sql("properties", "temporary_properties", None),
                EVENTS_PROPERTIES_JSON_TYPE(),
                EVENT_DOCUMENTS,
            ),
            (
                "person",
                "person_properties",
                person_document_sql("person_properties"),
                PERSON_PROPERTIES_JSON_TYPE(),
                PERSON_DOCUMENTS,
            ),
        ]
    )
    def test_document_keeps_sent_empties_and_drops_declared_defaults(
        self, _name: str, column: str, document_sql: str, json_type: str, cases: list[tuple[dict, dict | None]]
    ) -> None:
        rows = sync_execute(
            f"SELECT {document_sql} FROM (SELECT CAST(arrayJoin(%(documents)s), %(json_type)s) AS {column}, "
            f"CAST('{{}}', %(temporary_type)s) AS temporary_properties)",
            {
                "documents": [json.dumps(document) for document, _ in cases],
                "json_type": json_type,
                "temporary_type": TEMPORARY_PROPERTIES_JSON_TYPE,
            },
        )
        assert [json.loads(row[0]) for row in rows] == [
            expected if expected is not None else document for document, expected in cases
        ]
