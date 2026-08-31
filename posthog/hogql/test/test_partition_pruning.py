from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.partition_pruning import UnprunedEventsScan, find_unpruned_events_scans


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
            ("ordering cannot stop at the limit", "SELECT * FROM events ORDER BY timestamp DESC", 1),
            ("a filter defeats early termination", "SELECT * FROM events WHERE event = 'never_matches' LIMIT 1", 1),
            ("an offset still reads what it skips", "SELECT * FROM events LIMIT 10 OFFSET 500", 1),
            ("an inline window orders the partition first", "SELECT count() OVER () FROM events LIMIT 1", 1),
            (
                "a join can exhaust its input before a row matches",
                "SELECT * FROM events JOIN persons ON persons.id = events.person_id LIMIT 1",
                1,
            ),
            (
                "a cte body reads the real table it shadows",
                "WITH events AS (SELECT count() FROM events) SELECT * FROM events",
                1,
            ),
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


class TestUnprunedScanQuickFix(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "no where clause",
                "SELECT count() FROM events",
                "SELECT count() FROM events WHERE timestamp > now() - INTERVAL 30 DAY",
            ),
            (
                "existing where clause",
                "SELECT count() FROM events WHERE event = 'x'",
                "SELECT count() FROM events WHERE (event = 'x') AND timestamp > now() - INTERVAL 30 DAY",
            ),
            (
                "or keeps its own grouping",
                "SELECT count() FROM events WHERE a = 1 OR b = 2",
                "SELECT count() FROM events WHERE (a = 1 OR b = 2) AND timestamp > now() - INTERVAL 30 DAY",
            ),
            (
                "clause after the from",
                "SELECT count() FROM events GROUP BY event",
                "SELECT count() FROM events WHERE timestamp > now() - INTERVAL 30 DAY GROUP BY event",
            ),
            (
                "join writes past the constraint and qualifies the column",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id GROUP BY e.event",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id"
                " WHERE e.timestamp > now() - INTERVAL 30 DAY GROUP BY e.event",
            ),
            (
                "subquery holding the scan",
                "SELECT count() FROM (SELECT * FROM events)",
                "SELECT count() FROM (SELECT * FROM events WHERE timestamp > now() - INTERVAL 30 DAY)",
            ),
            ("prewhere has no unambiguous insertion point", "SELECT count() FROM events PREWHERE event = 'x'", None),
            (
                "left join writes into the on clause, not the where",
                "SELECT count() FROM persons LEFT JOIN events ON persons.id = events.person_id",
                "SELECT count() FROM persons LEFT JOIN events"
                " ON (persons.id = events.person_id) AND events.timestamp > now() - INTERVAL 30 DAY",
            ),
            (
                "left join uses the alias",
                "SELECT count() FROM persons LEFT JOIN events e ON persons.id = e.person_id",
                "SELECT count() FROM persons LEFT JOIN events e"
                " ON (persons.id = e.person_id) AND e.timestamp > now() - INTERVAL 30 DAY",
            ),
            (
                "inner join takes the where and qualifies the column",
                "SELECT count() FROM persons JOIN events ON persons.id = events.person_id",
                "SELECT count() FROM persons JOIN events ON persons.id = events.person_id"
                " WHERE events.timestamp > now() - INTERVAL 30 DAY",
            ),
            (
                "an alias needing escapes is quoted",
                'SELECT count() FROM events AS "e-x"',
                'SELECT count() FROM events AS "e-x" WHERE `e-x`.timestamp > now() - INTERVAL 30 DAY',
            ),
            (
                "using lists columns, so no conjunct fits",
                "SELECT count() FROM persons LEFT JOIN events USING person_id",
                None,
            ),
            (
                "right join leaves which side survives unclear",
                "SELECT count() FROM persons RIGHT JOIN events ON persons.id = events.person_id",
                None,
            ),
            (
                "full join leaves which side survives unclear",
                "SELECT count() FROM persons FULL OUTER JOIN events ON persons.id = events.person_id",
                None,
            ),
        ]
    )
    def test_quick_fix_edits(self, _name: str, query: str, expected: str | None) -> None:
        [scan] = find_unpruned_events_scans(parse_select(query))

        if expected is None:
            self.assertEqual(scan.bound_edits, ())
            return

        fixed = _apply_edits(query, scan)
        self.assertEqual(fixed, expected)
        parse_select(fixed)
        self.assertEqual(find_unpruned_events_scans(parse_select(fixed)), [])


def _apply_edits(query: str, scan: UnprunedEventsScan) -> str:
    text, offset = query, 0
    for edit in sorted(scan.bound_edits, key=lambda edit: edit.start):
        text = text[: edit.start + offset] + edit.text + text[edit.end + offset :]
        offset += len(edit.text) - (edit.end - edit.start)
    return text
