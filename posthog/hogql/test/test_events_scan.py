from unittest import TestCase

from parameterized import parameterized

from posthog.hogql.database.database import Database
from posthog.hogql.events_scan import EventsScanReason, find_events_scans
from posthog.hogql.parser import parse_select

# The default schema resolves `events` without a team or a database connection
DATABASE = Database()


def reasons(query: str) -> list[EventsScanReason]:
    return [finding.reason for finding in find_events_scans(parse_select(query), DATABASE)]


class TestFindEventsScans(TestCase):
    @parameterized.expand(
        [
            (
                "property filter only",
                "SELECT count() FROM events WHERE properties.plan = 'pro' AND timestamp >= now() - INTERVAL 7 DAY",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "bracket property access",
                "SELECT count() FROM events WHERE properties['plan'] = 'pro' AND timestamp >= now() - INTERVAL 7 DAY",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "property wrapped in a function",
                "SELECT count() FROM events WHERE toString(properties.plan) = 'pro' AND timestamp >= today() - 1",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "aliased table and person property",
                "SELECT count() FROM events e WHERE e.person.properties.email = 'x' AND e.timestamp >= today()",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "event name filter makes the property filter fine",
                "SELECT count() FROM events WHERE event = 'paid' AND properties.plan = 'pro' AND timestamp >= today()",
                [],
            ),
            (
                "event IN list and function-style comparisons",
                "SELECT count() FROM events e WHERE in(e.event, ('a', 'b')) AND greaterOrEquals(e.timestamp, today())",
                [],
            ),
            (
                "OR where one side has no event name",
                "SELECT count() FROM events WHERE (event = 'a' OR properties.plan = 'pro') AND timestamp >= today()",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "OR where both sides name the event",
                "SELECT count() FROM events WHERE (event = 'a' OR event = 'b') AND timestamp >= today()",
                [],
            ),
            (
                "negated event filter does not prune",
                "SELECT count() FROM events WHERE event != 'a' AND properties.plan = 'pro' AND timestamp >= today()",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "no filter at all",
                "SELECT count() FROM events",
                [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "all events in a range is only a notice-level finding",
                "SELECT event, count() FROM events WHERE timestamp >= now() - INTERVAL 7 DAY GROUP BY event",
                [EventsScanReason.NO_EVENT_FILTER],
            ),
            (
                "upper bound alone does not bound the history",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp < now()",
                [EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "monotonic wrapper on timestamp still counts as a bound",
                "SELECT count() FROM events WHERE event = 'a' AND toDate(timestamp) >= '2025-01-01'",
                [],
            ),
            (
                "bound on the right-hand side",
                "SELECT count() FROM events WHERE event = 'a' AND '2025-01-01' <= timestamp",
                [],
            ),
            (
                "dateDiff cannot use the sort key",
                "SELECT count() FROM events WHERE event = 'a' AND dateDiff('day', timestamp, now()) < 7",
                [EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "property filter in a person subquery belongs to persons",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp >= today() "
                "AND person_id IN (SELECT id FROM persons WHERE properties.email = 'x')",
                [],
            ),
            (
                "CTE named events shadows the table",
                "WITH events AS (SELECT 1 AS x) SELECT count() FROM events WHERE x = 1",
                [],
            ),
            (
                "other tables are not checked",
                "SELECT count() FROM persons WHERE properties.email = 'x'",
                [],
            ),
        ]
    )
    def test_reasons(self, _name: str, query: str, expected: list[EventsScanReason]) -> None:
        self.assertEqual(reasons(query), expected)

    def test_reports_each_events_read_in_ctes_and_subqueries(self) -> None:
        query = (
            "WITH subs AS (SELECT person_id FROM events WHERE properties.kind = 'sub' AND timestamp >= today() - 400) "
            "SELECT count() FROM events WHERE person_id IN (SELECT person_id FROM subs) AND timestamp >= today() - 400"
        )
        self.assertEqual(
            reasons(query),
            [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
        )

    def test_finding_marks_the_events_reference_and_names_the_property(self) -> None:
        query = "SELECT count() FROM events WHERE properties.plan = 'pro' AND properties['tier'] = 'a' AND timestamp >= today()"
        (finding,) = find_events_scans(parse_select(query), DATABASE)
        self.assertEqual(query[finding.start : finding.end], "events")
        self.assertEqual(finding.property_names, ("plan", "tier"))
