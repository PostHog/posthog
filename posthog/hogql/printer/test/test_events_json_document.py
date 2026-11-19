import json

import pytest

from django.test import SimpleTestCase

from posthog.hogql.printer.events_json_document import (
    EVENTS_PROPERTIES_DECLARED_STRING_PATHS,
    PERSON_PROPERTIES_DECLARED_STRING_PATHS,
    event_document_sql,
    json_document_sql,
    person_document_sql,
)
from posthog.hogql.test.utils import native_stored_document

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import TEMPORARY_PROPERTIES_JSON_TYPE
from posthog.models.event.sql import (
    EVENTS_JSON_CLEANER,
    EVENTS_PROPERTIES_JSON_TYPE,
    PERSON_PROPERTIES_JSON_TYPE,
    _cast_cleaned_properties,
    _cast_temporary_properties,
)

# The event properties and person properties an SDK sent, then the rebuilt documents where they differ from what was
# sent. A sent empty value under a dynamic key stays; a declared string path reads '' whether sent empty or absent,
# so the document leaves it out. A property sent as null is left out. A null inside an object stays.
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
        {"$exception_types": [], "custom_list": [], "note": ""},
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
        {
            "billing": {"coupon": None, "seats": 3, "card": {"brand": None}},
            "trial": {"ends": None},
            "$set": {"email": None, "name": "n"},
            "$set_once": {"first": None},
        },
        {"profile": {"org": {"size": None, "seats": 5}}, "geo": {"city.name": None}},
    ),
    (
        {"path": ["app/models/user.py"], "text": "[not json", "quoted": '{"a":1}'},
        {"tags": [{"name": "a/b"}]},
        # A string that holds a JSON object reads as that object: nothing records which strings the cleaner wrote.
        {"path": ["app/models/user.py"], "text": "[not json", "quoted": {"a": 1}},
        None,
    ),
]

# The event properties and person properties an SDK sent, for each rule of the export cleaner. They are JSON text and
# not dicts, because several rules depend on how a number is written.
EXPORT_PARITY_DOCUMENTS: dict[str, tuple[str, str]] = {
    "objects, arrays and nulls": (
        '{"plan":{"seats":5,"trial":null,"price":2.0},"path":["a/b",null,{"deep":[]}],"empty_object":{},'
        '"empty_array":[],"sent_null":null,"note":""}',
        '{"address":{"city":null,"zip":"1"},"tags":[],"gone":null}',
    ),
    "a number under every declared string path": (
        json.dumps(dict.fromkeys(EVENTS_PROPERTIES_DECLARED_STRING_PATHS, 7)),
        json.dumps(dict.fromkeys(PERSON_PROPERTIES_DECLARED_STRING_PATHS, 7)),
    ),
    "an empty string under every declared string path": (
        json.dumps(dict.fromkeys(EVENTS_PROPERTIES_DECLARED_STRING_PATHS, "")),
        json.dumps(dict.fromkeys(PERSON_PROPERTIES_DECLARED_STRING_PATHS, "")),
    ),
    "other values under declared string paths": (
        '{"$browser_version":1.50,"$lib_version":1e3,"$os":true,"$pathname":-0.0,"$host":{"a":1},'
        '"$session_id":1e-7,"$window_id":1e21,"$current_url":"[1,2]"}',
        '{"$browser":0.1e1,"$initial_os":false,"$os_version":["a"]}',
    ),
    "feature flags": (
        '{"$feature/beta":true,"$feature/variant":"control","$feature/named-true":"true","$feature/count":1e3,'
        '"$feature/off":null,"$feature_flags":{"old":"x","object":{"z":1.0,"path":"a/b","n":null},'
        '"list":[1.50,null,"s"]},"$active_feature_flags":["beta"]}',
        '{"$feature_flags":{"p":1}}',
    ),
    "an empty flags map": ('{"$feature_flags":{},"k":1}', "{}"),
    "a flags value that is not an object": ('{"$feature_flags":"text","k":1}', "{}"),
    "temporary properties": (
        '{"$set":{"email":"a@example.com","n":null},"$set_once":{},"$unset":["a"],"$sdk_debug_probe":1.50,'
        '"$group_set":null,"custom":"kept"}',
        "{}",
    ),
    "strings that look like JSON": (
        json.dumps(
            {
                "array": "[1,2]",
                "object": '{"a": 1}',
                "cut": "[1,2",
                "leading_space": " [1]",
                "two_documents": "{}{}",
                "out_of_range": "[1e400]",
                "lone_surrogate": '["\\ud800"]',
                "surrogate_pair": '["\\ud83d\\ude00"]',
                "text": "plain",
            }
        ),
        '{"tags":"[\\"a\\"]"}',
    ),
    "dots in keys": ('{"a.b":1,"a%2Eb":2,"c%2Ed":3,"c.d":4,"lower%2e":5}', '{"x%2Ey":"v"}'),
    "numbers near the 64-bit and Float64 limits": (
        '{"fits":1e19,"too_big":2e19,"too_small":-1e19,"exponent":1e21,"fraction":1.50,'
        '"uint":18446744073709551615,"beyond":18446744073709551616,"negative_zero":-0.0,"tiny":1e-999,'
        '"precise":0.30000000000000004441,"rounded":12345678901234567890.0}',
        '{"too_big":123456789012345678901.5}',
    ),
    "an out-of-range number": ('{"k":1e400,"$set":{"a":1}}', '{"n":-1e400,"m":1}'),
    "an out-of-range temporary number": ('{"k":1,"$sdk_debug_probe":1e400,"$set":{"a":1}}', "{}"),
    "an out-of-range number in the flags map": ('{"$feature_flags":{"f":{"deep":[1e400]}},"k":1}', "{}"),
    "an out-of-range number inside an object": ('{"o":{"n":1e400,"m":1}}', "{}"),
    "blank": ("", "  "),
    "malformed": ('{"broken"', "[1"),
    "not an object": ("[1,2]", '"text"'),
    "duplicate keys": ('{"a":1,"a":2,"b":"","b":3}', '{"a":null,"a":1}'),
    "escaped characters": (
        '{"control":"\\u0001\\u001f","quote":"\\"\\\\","separator":"\\u2028","nested":{"s":"\\u0001\\"\\\\/"}}',
        "{}",
    ),
}


@pytest.mark.usefixtures("clickhouse_database")
class TestEventsJsonDocument(SimpleTestCase):
    def test_rebuilt_documents_match_what_the_sdk_sent(self) -> None:
        documents = event_document_sql("properties", "temporary_properties", "properties.`$feature_flags`")
        person_documents = person_document_sql("person_properties")
        rows = sync_execute(
            f"SELECT {documents}, {person_documents} FROM ("
            "SELECT CAST(cleaned.properties, %(event_type)s) AS properties, "
            "CAST(cleaned.temporary_properties, %(temporary_type)s) AS temporary_properties, "
            "CAST(cleaned.person_properties, %(person_type)s) AS person_properties "
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

    def test_native_stored_document_matches_the_cleaner(self) -> None:
        sent = (
            '{"plan": {"tier": "pro", "seats": 5, "trial": null, "price": 2.0, "ratio": 1e-7, '
            '"id": 123456789012345678901234567890, "tier": "duplicate"}, '
            '"tags": ["b", null, {"z": 1E3, "a": "caf\\u00e9 a\\/b \\u001f"}], "count": 2.0, "name": "x"}'
        )
        [[cleaned]] = sync_execute(f"SELECT {EVENTS_JSON_CLEANER}(%(sent)s, '{{}}').properties", {"sent": sent})
        assert json.loads(cleaned) == json.loads(native_stored_document(sent))

    def test_export_cleaner_matches_a_read_of_the_stored_columns(self) -> None:
        stored_properties = json_document_sql(
            "properties",
            exclude_empty_key="$feature_flags",
            declared_string_paths=EVENTS_PROPERTIES_DECLARED_STRING_PATHS,
        )
        event_cast = _cast_cleaned_properties("properties", "source.properties", EVENTS_PROPERTIES_JSON_TYPE())
        person_cast = _cast_cleaned_properties(
            "person_properties", "source.person_properties", PERSON_PROPERTIES_JSON_TYPE()
        )
        rows = sync_execute(
            f"SELECT {stored_properties}, {json_document_sql('temporary_properties')}, "
            f"{person_document_sql('person_properties')}, "
            "properties_null_keys, temporary_properties_null_keys, person_properties_null_keys, "
            "exported.properties, exported.temporary_properties, exported.person_properties, "
            "exported.properties_null_keys, exported.temporary_properties_null_keys, "
            "exported.person_properties_null_keys "
            f"FROM (SELECT {event_cast} AS properties, "
            f"{_cast_temporary_properties('temporary_properties')} AS temporary_properties, "
            f"{person_cast} AS person_properties, "
            "cleaned.properties_null_keys AS properties_null_keys, "
            "cleaned.temporary_properties_null_keys AS temporary_properties_null_keys, "
            "cleaned.person_properties_null_keys AS person_properties_null_keys, exported "
            f"FROM (SELECT sent.1 AS properties, sent.2 AS person_properties, "
            f"{EVENTS_JSON_CLEANER}(properties, person_properties) AS cleaned, "
            "JSONCleanPostHogEventForExport(properties, person_properties) AS exported "
            "FROM (SELECT arrayJoin(%(sent)s) AS sent)) AS source)",
            {"sent": list(EXPORT_PARITY_DOCUMENTS.values())},
            settings={
                "input_format_try_infer_dates": 0,
                "input_format_try_infer_datetimes": 0,
                "json_type_escape_dots_in_keys": 1,
                "type_json_skip_duplicated_paths": 1,
            },
        )

        # ClickHouse prints a Float64 in its own spelling, and the cleaner keeps the number as it was sent.
        def loads(document: str):
            return json.loads(document, parse_int=float)

        read_of_stored_columns = {}
        exported = {}
        for name, row in zip(EXPORT_PARITY_DOCUMENTS, rows):
            temporary = loads(row[1])
            read_of_stored_columns[name] = ({**loads(row[0]), **temporary}, temporary, loads(row[2]), *row[3:6])
            exported[name] = (loads(row[6]), loads(row[7]), loads(row[8]), *row[9:12])
        assert exported == read_of_stored_columns
