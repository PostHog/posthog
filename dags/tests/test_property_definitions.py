import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.models.property_definition import PropertyDefinition

from dags.property_definitions import (
    DetectPropertyTypeExpression,
    PropertyDefinitionsConfig,
    property_definitions_ingestion_job,
    setup_job,
)


@dataclass
class PropertyTypeTestData:
    properties: str
    expected: list[tuple[str, str | None]]


def test_detect_property_type_expression(cluster: ClickhouseCluster) -> None:
    cases = {
        UUID(int=i): case
        for i, case in enumerate(
            [
                PropertyTypeTestData("{}", []),
                # special cases: key patterns
                PropertyTypeTestData('{"utm_source": 123}', [("utm_source", "String")]),
                PropertyTypeTestData('{"$feature/a": false}', [("$feature/a", "String")]),
                PropertyTypeTestData(
                    '{"$survey_response": 1, "$survey_response_2": 2}',
                    [("$survey_response", "String"), ("$survey_response_2", "String")],
                ),
                # special cases: timestamp detection
                PropertyTypeTestData(
                    json.dumps({"timestamp": time.time()}),
                    [("timestamp", "DateTime")],  # XXX: can't be parsed back out correctly!
                ),
                PropertyTypeTestData(json.dumps({"timestamp": int(time.time())}), [("timestamp", "DateTime")]),
                PropertyTypeTestData(
                    json.dumps({"timestamp": time.time() - timedelta(days=365).total_seconds()}),
                    [("timestamp", "Numeric")],  # "too old"
                ),
                # special cases: string values
                PropertyTypeTestData('{"a": "true"}', [("a", "Boolean")]),
                PropertyTypeTestData('{"a": "TRUE"}', [("a", "Boolean")]),
                PropertyTypeTestData('{"a": "false"}', [("a", "Boolean")]),
                PropertyTypeTestData('{"a": "FALSE"}', [("a", "Boolean")]),
                PropertyTypeTestData('{"a": " true "}', [("a", "Boolean")]),
                PropertyTypeTestData(
                    '{"a": "true\\n"}',
                    [("a", "String")],  # XXX: inconsistent with existing implementation
                ),
                PropertyTypeTestData(  # weird formats clickhouse allows
                    '{"a": "23:21:04", "b": "September", "c": "2024", "d": "1"}',
                    [("a", "String"), ("b", "String"), ("c", "String"), ("d", "String")],
                ),
                PropertyTypeTestData('{"a": "2025-04-24"}', [("a", "DateTime")]),
                PropertyTypeTestData('{"a": "04/24/2025"}', [("a", "DateTime")]),
                PropertyTypeTestData(
                    '{"a": "2025-04-24 23:21:04"}',  # ISO-8601, space separator, no tz
                    [("a", "DateTime")],
                ),
                PropertyTypeTestData(
                    '{"a": "2025-04-24T23:21:04+0000"}',  # ISO-8601, t separator, with tz
                    [("a", "DateTime")],
                ),
                PropertyTypeTestData(
                    '{"a": "2025-04-24T23:21:04+00:00"}',  # RFC 3339
                    [("a", "DateTime")],
                ),
                PropertyTypeTestData(
                    '{"a": "Thu, 24 Apr 2025 23:21:04 +0000"}',  # RFC 2822
                    [("a", "DateTime")],
                ),
                PropertyTypeTestData(
                    json.dumps({"a": str(time.time())}),
                    [("a", "String")],  # skip timestamp-like formats
                ),
                PropertyTypeTestData(
                    json.dumps({"a": str(int(time.time()))}),
                    [("a", "String")],  # skip timestamp-like formats
                ),
                # primitive types
                PropertyTypeTestData('{"a": true}', [("a", "Boolean")]),
                PropertyTypeTestData('{"a": false}', [("a", "Boolean")]),
                PropertyTypeTestData('{"a": 0}', [("a", "Numeric")]),
                PropertyTypeTestData('{"a": 1}', [("a", "Numeric")]),
                PropertyTypeTestData('{"a": -1}', [("a", "Numeric")]),
                PropertyTypeTestData('{"a": 3.14}', [("a", "Numeric")]),
                PropertyTypeTestData('{"a": "x"}', [("a", "String")]),
                PropertyTypeTestData('{"a": [1,2,3]}', [("a", None)]),
                PropertyTypeTestData('{"a": {"k": "v"}}', [("a", None)]),
                PropertyTypeTestData('{"a": null}', [("a", None)]),
            ]
        )
    }

    cluster.any_host(
        Query(
            f"INSERT INTO writable_events (uuid, properties) VALUES",
            [(uuid, case.properties) for uuid, case in cases.items()],
        )
    ).result()

    results = cluster.any_host(Query(f"SELECT uuid, {DetectPropertyTypeExpression('properties')} FROM events")).result()
    for uuid, actual in results:
        case = cases[uuid]
        assert actual == case.expected, f"expected {case.expected} for {case.properties}, got {actual}"


def test_ingestion_job(cluster: ClickhouseCluster) -> None:
    start_at = datetime(2025, 5, 7)
    duration = timedelta(hours=1)

    # insert test data
    cluster.any_host(
        Query(
            f"INSERT INTO events_recent (uuid, team_id, event, timestamp, properties) VALUES",
            [
                (UUID(int=i), 1, event, timestamp, json.dumps(properties))
                for i, (event, timestamp, properties) in enumerate(
                    [
                        ("event", start_at - timedelta(minutes=30), {"too_old": "1"}),  # out of range (too old)
                        ("event", start_at, {"property": 1}),  # lower bound, should be included
                        ("a" * 201, start_at, {"event_name_too_long": 1}),  # event name too long, should be skipped
                        ("\u0000", start_at, {"property": 1}),  # null byte should be sanitized
                        ("event", start_at, {"p" * 201: 1}),  # property name too long, should be skipped
                        ("$$plugin_metrics", start_at, {"property": 1}),  # skipped event
                        (
                            "event",
                            start_at + duration * 0.5,  # midpoint
                            {"property": 1, "$set": {}},  # includes skipped property
                        ),
                        (
                            "event",
                            start_at + duration * 0.75,
                            {"property": None},
                        ),  # prior updates with detected types should take precedence
                        ("event", start_at + duration, {"too_new": 1}),  # upper bound, should be excluded
                        (
                            "event",
                            start_at + duration + timedelta(minutes=30),  # out of range (too new)
                            {"too_new": 1},
                        ),
                    ]
                )
            ],
        )
    ).result()

    cluster.any_host(
        Query(
            f"INSERT INTO person (team_id, id, _timestamp, properties) VALUES",
            [
                (1, UUID(int=i), timestamp, json.dumps(properties))
                for i, (timestamp, properties) in enumerate(
                    [
                        (start_at - timedelta(minutes=30), {"too_old": "1"}),  # out of range (too old)
                        (start_at, {"property": 1}),  # lower bound, should be included
                        (start_at, {"p" * 201: 1}),  # property name too long, should be skipped
                        (
                            start_at + duration * 0.5,  # midpoint
                            {"property": 1},  # includes skipped property
                        ),
                        (
                            start_at + duration * 0.75,
                            {"property": None},
                        ),  # prior updates with detected types should take precedence
                        (start_at + duration, {"too_new": 1}),  # upper bound, should be excluded
                        (start_at + duration + timedelta(minutes=30), {"too_new": 1}),  # out of range (too new)
                    ]
                )
            ],
        )
    ).result()

    cluster.any_host(
        Query(
            f"INSERT INTO groups (team_id, group_key, group_type_index, _timestamp, group_properties) VALUES",
            [
                (1, UUID(int=i).hex, group_type_index, timestamp, json.dumps(properties))
                for i, (group_type_index, timestamp, properties) in enumerate(
                    [
                        (1, start_at - timedelta(minutes=30), {"too_old": "1"}),  # out of range (too old)
                        (1, start_at, {"property": 1}),  # lower bound, should be included
                        (1, start_at, {"p" * 201: 1}),  # property name too long, should be skipped
                        (
                            1,
                            start_at + duration * 0.5,  # midpoint
                            {"property": 1},  # includes skipped property
                        ),
                        (
                            1,
                            start_at + duration * 0.75,
                            {"property": None},
                        ),  # prior updates with detected types should take precedence
                        (1, start_at + duration, {"too_new": 1}),  # upper bound, should be excluded
                        (1, start_at + duration + timedelta(minutes=30), {"too_new": 1}),  # out of range (too new)
                        (2, start_at, {"property": 1}),  # lower bound, should be included
                    ]
                )
            ],
        )
    ).result()

    # run job
    config = PropertyDefinitionsConfig(
        start_at=start_at.isoformat(),
        duration=f"{duration.total_seconds():.0f} seconds",
    )
    property_definitions_ingestion_job.execute_in_process(
        run_config=dagster.RunConfig({setup_job.name: config}),
        resources={"cluster": cluster},
    )

    # check results
    assert cluster.any_host(
        Query(
            """
            SELECT team_id, project_id, name, property_type, event, group_type_index, type, last_seen_at
            FROM property_definitions
            ORDER BY ALL
            """
        ),
    ).result() == [
        (1, 1, "property", "Numeric", "event", None, int(PropertyDefinition.Type.EVENT), start_at + duration / 2),
        (1, 1, "property", "Numeric", "\ufffd", None, int(PropertyDefinition.Type.EVENT), start_at),
        (1, 1, "property", "Numeric", None, 1, int(PropertyDefinition.Type.GROUP), start_at + duration / 2),
        (1, 1, "property", "Numeric", None, 2, int(PropertyDefinition.Type.GROUP), start_at),
        (1, 1, "property", "Numeric", None, None, int(PropertyDefinition.Type.PERSON), start_at + duration / 2),
    ]
