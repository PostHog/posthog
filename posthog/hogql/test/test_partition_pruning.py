from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.partition_pruning import find_unpruned_events_scans


class TestFindUnprunedEventsScans(SimpleTestCase):
    @parameterized.expand(
        [
            ("aggregate over the whole table", "SELECT count() FROM events", 1),
            ("relative lower bound", "SELECT count() FROM events WHERE timestamp > now() - INTERVAL 30 DAY", 0),
            (
                "interval arithmetic on the bound",
                "SELECT count() FROM events WHERE timestamp + INTERVAL 1 DAY > now()",
                0,
            ),
            (
                "between bounds both sides",
                "SELECT count() FROM events WHERE timestamp BETWEEN '2024-01-01' AND '2024-02-01'",
                0,
            ),
            ("order preserving wrapper", "SELECT count() FROM events WHERE toStartOfDay(timestamp) >= '2024-01-01'", 0),
            ("date truncation wrapper", "SELECT count() FROM events WHERE toDate(timestamp) = '2024-01-01'", 0),
            ("non monotonic wrapper", "SELECT count() FROM events WHERE toDayOfWeek(timestamp) = 3", 1),
            ("inequality is not a range", "SELECT count() FROM events WHERE timestamp != now()", 1),
            ("one or branch unbounded", "SELECT count() FROM events WHERE event = 'x' OR timestamp > now()", 1),
            (
                "every or branch bounded",
                "SELECT count() FROM events WHERE timestamp > now() OR timestamp < '2020-01-01'",
                0,
            ),
            ("group by reads every row", "SELECT event, count() FROM events GROUP BY event", 1),
            ("implicit top level limit", "SELECT * FROM events", 0),
            ("ordering follows the sort key", "SELECT * FROM events ORDER BY timestamp DESC", 0),
            ("ordering off the sort key", "SELECT * FROM events ORDER BY event DESC", 1),
            ("outer bound reaches the scan", "SELECT count() FROM (SELECT * FROM events) WHERE timestamp > now()", 0),
            ("subquery under an aggregate", "SELECT count() FROM (SELECT * FROM events)", 1),
            ("limit carries into a streaming subquery", "SELECT * FROM (SELECT * FROM events) LIMIT 10", 0),
            ("limit stops at a sorting subquery", "SELECT * FROM (SELECT * FROM events ORDER BY event) LIMIT 10", 1),
            (
                "limit does not cap an in subquery",
                "SELECT id FROM persons WHERE id IN (SELECT person_id FROM events) LIMIT 10",
                1,
            ),
            ("cte named events shadows the table", "WITH events AS (SELECT 1 AS a) SELECT count() FROM events", 0),
            ("scan inside a cte body", "WITH e AS (SELECT * FROM events) SELECT count() FROM e", 1),
            ("another table", "SELECT count() FROM persons", 0),
            ("every branch of a union", "SELECT count() FROM events UNION ALL SELECT count() FROM events", 2),
        ]
    )
    def test_scan_classification(self, _name: str, query: str, expected: int) -> None:
        self.assertEqual(len(find_unpruned_events_scans(parse_select(query))), expected)

    def test_reports_the_position_of_the_events_reference(self) -> None:
        query = "SELECT count() FROM events"

        scans = find_unpruned_events_scans(parse_select(query))

        self.assertEqual(len(scans), 1)
        self.assertEqual(query[scans[0].start : scans[0].end], "events")
