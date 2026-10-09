import json

import pytest

from django.test import SimpleTestCase

from posthog.hogql.printer.events_json_document import event_document_sql, person_document_sql

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import TEMPORARY_PROPERTIES_JSON_TYPE
from posthog.models.event.sql import EVENTS_JSON_CLEANER, EVENTS_PROPERTIES_JSON_TYPE, PERSON_PROPERTIES_JSON_TYPE

# The event properties and person properties an SDK sent, then the rebuilt documents where they differ from what was
# sent. A sent empty value under a dynamic key stays; the declared paths read '' or [] whether sent empty or absent,
# so the document leaves those out. A field sent as null comes back as null wherever it sat.
SENT_DOCUMENTS: list[tuple[dict, dict, dict | None, dict | None]] = [
    (
        {"$browser": "Chrome", "pathname": "/docs", "empty": "", "list": [], "nested": {"child": ""}},
        {"$initial_browser": "Chrome", "email": "a@example.com", "empty": "", "list": []},
        None,
        None,
    ),
    (
        {"$browser": "", "$exception_types": [], "custom_list": [], "note": ""},
        {"$initial_browser": "", "$browser": "", "list": [], "note": ""},
        {"custom_list": [], "note": ""},
        {"list": [], "note": ""},
    ),
    ({}, {}, None, None),
    (
        {
            "plan": None,
            "a.b": None,
            "$browser": None,
            "$feature/beta": None,
            "billing": {"coupon": None, "seats": 3, "card": {"brand": None}},
            "trial": {"ends": None},
            "$set": {"email": None, "name": "n"},
            "$set_once": {"first": None},
        },
        {"team": None, "profile": {"org": {"size": None, "seats": 5}}, "geo": {"city.name": None}},
        None,
        None,
    ),
    (
        {
            "items": [{"sku": "a", "note": None}, {"sku": "b"}, {"gone": None}],
            "matrix": [[{"x": None, "y": 1}]],
            "list": [1, None],
            "$exception_list": [{"type": "E", "value": "v", "stacktrace": {"frames": [{"lineno": None, "f": "g"}]}}],
            "$group_set": {"modules": [{"owner": None, "name": "m1"}]},
        },
        {"years": {"2024": {"x": None}, "2025": 1}},
        None,
        None,
    ),
]


@pytest.mark.usefixtures("clickhouse_database")
class TestEventsJsonDocument(SimpleTestCase):
    def test_rebuilt_documents_match_what_the_sdk_sent(self) -> None:
        documents = event_document_sql(
            "properties",
            "properties_null_keys",
            "temporary_properties",
            "temporary_properties_null_keys",
            "properties.`$feature_flags`",
        )
        person_documents = person_document_sql("person_properties", "person_properties_null_keys")
        rows = sync_execute(
            f"SELECT {documents}, {person_documents} FROM ("
            "SELECT CAST(cleaned.properties, %(event_type)s) AS properties, "
            "CAST(cleaned.temporary_properties, %(temporary_type)s) AS temporary_properties, "
            "CAST(cleaned.person_properties, %(person_type)s) AS person_properties, "
            "cleaned.properties_null_keys AS properties_null_keys, "
            "cleaned.temporary_properties_null_keys AS temporary_properties_null_keys, "
            "cleaned.person_properties_null_keys AS person_properties_null_keys "
            f"FROM (SELECT {EVENTS_JSON_CLEANER}(sent.1, sent.2) AS cleaned FROM (SELECT arrayJoin(%(sent)s) AS sent)))",
            {
                "sent": [(json.dumps(event), json.dumps(person)) for event, person, _, _ in SENT_DOCUMENTS],
                "event_type": EVENTS_PROPERTIES_JSON_TYPE(),
                "temporary_type": TEMPORARY_PROPERTIES_JSON_TYPE,
                "person_type": PERSON_PROPERTIES_JSON_TYPE(),
            },
            settings={
                "input_format_try_infer_dates": 0,
                "input_format_try_infer_datetimes": 0,
                "json_type_escape_dots_in_keys": 1,
                "type_json_skip_duplicated_paths": 1,
            },
        )
        assert [(json.loads(event), json.loads(person)) for event, person in rows] == [
            (
                event if expected_event is None else expected_event,
                person if expected_person is None else expected_person,
            )
            for event, person, expected_event, expected_person in SENT_DOCUMENTS
        ]
