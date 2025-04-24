import json
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from dags.tests.conftest import cluster
from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.property_definitions.clickhouse import DETECT_PROPERTY_TYPE_EXPR


cluster  # noqa: B018; need to move fixture to fix discovery


@dataclass
class PropertyTypeTestData:
    properties: str
    expected: list[tuple[str, str | None]]


def test_detect_property_type_expr(cluster: ClickhouseCluster) -> None:
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

    results = cluster.any_host(Query(f"SELECT uuid, {DETECT_PROPERTY_TYPE_EXPR} FROM events")).result()
    for uuid, actual in results:
        case = cases[uuid]
        assert actual == case.expected, f"expected {case.expected} for {case.properties}, got {actual}"
