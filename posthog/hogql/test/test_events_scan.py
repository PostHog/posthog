from unittest import TestCase

from parameterized import parameterized

from posthog.hogql.database.database import Database
from posthog.hogql.events_scan import (
    EventsScanReason,
    EventsScanSource,
    attribute_findings,
    find_events_scans,
    finding_fix,
    finding_message,
)
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
                "BETWEEN bounds the timestamp",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp BETWEEN '2025-01-01' AND '2025-02-01'",
                [],
            ),
            (
                "function-call and() form",
                "SELECT count() FROM events WHERE and(equals(event, 'a'), greaterOrEquals(timestamp, today()))",
                [],
            ),
            (
                "filters in the JOIN ON clause",
                "SELECT count() FROM persons p JOIN events e ON e.person_id = p.id AND e.event = 'a' AND e.timestamp >= today()",
                [],
            ),
            (
                "{filters} supplies the date range",
                "SELECT count() FROM events WHERE event = 'a' AND {filters}",
                [],
            ),
            (
                "{filters} does not stand in for an event name",
                "SELECT count() FROM events WHERE properties.plan = 'pro' AND {filters}",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "dateTrunc and toStartOf wrappers still count as bounds",
                "SELECT count() FROM events WHERE event = 'a' AND dateTrunc('day', timestamp) >= '2025-01-01' AND toStartOfFifteenMinutes(timestamp) >= '2025-01-01'",
                [],
            ),
            (
                "a CTE named events still checks its own body",
                "WITH events AS (SELECT count() AS c FROM events WHERE properties.plan = 'pro' AND timestamp >= today()) SELECT c FROM events",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "a root WITH shadows events in every UNION branch",
                "WITH events AS (SELECT 1 AS x) SELECT x FROM events UNION ALL SELECT x FROM events",
                [],
            ),
            (
                "a CTE named events still checks its own body across a UNION",
                "WITH events AS (SELECT count() AS c FROM events WHERE properties.plan = 'pro' AND timestamp >= today()) "
                "SELECT c FROM events UNION ALL SELECT 1 AS c",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "a CTE nobody reads is never substituted, so it reads nothing",
                "WITH unused AS (SELECT count() FROM events) SELECT 1",
                [],
            ),
            (
                "only the unread CTE is skipped",
                "WITH used AS (SELECT count() AS c FROM events), unused AS (SELECT count() FROM events) "
                "SELECT c FROM used",
                [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "a CTE read by another UNION branch still counts as read",
                "WITH a AS (SELECT count() AS c FROM events) SELECT 1 AS c UNION ALL SELECT c FROM a",
                [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "a CTE read from inside another CTE body still counts as read",
                "WITH a AS (SELECT count() AS c FROM events) "
                "SELECT x FROM (WITH b AS (SELECT c FROM a) SELECT c AS x FROM b)",
                [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "a nested CTE named events reads the CTE around it, not the table",
                "WITH events AS (SELECT 1 AS x) "
                "SELECT c FROM (WITH events AS (SELECT count() AS c FROM events) SELECT c FROM events)",
                [],
            ),
            (
                "a correlated column is no timestamp bound",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id "
                "WHERE e.event = 'a' AND e.timestamp >= p.created_at",
                [EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "a correlated column is no timestamp bound in function form",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id "
                "WHERE equals(e.event, 'a') AND greaterOrEquals(e.timestamp, p.created_at)",
                [EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "a column BETWEEN lower value is no timestamp bound",
                "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id "
                "WHERE e.event = 'a' AND e.timestamp BETWEEN p.created_at AND p.created_at",
                [EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "matching one events alias against another pins no event name",
                "SELECT count() FROM events a JOIN events b ON a.person_id = b.person_id AND a.event = b.event "
                "WHERE a.properties.plan = 'pro' AND a.timestamp >= today() AND b.timestamp >= today()",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT, EventsScanReason.NO_EVENT_FILTER],
            ),
            (
                "a scalar subquery still bounds the timestamp",
                "SELECT count() FROM events WHERE event = 'a' AND timestamp >= (SELECT max(created_at) FROM persons)",
                [],
            ),
            (
                "a select alias expands to a constant bound",
                "SELECT today() AS cutoff, count() FROM events WHERE event = 'a' AND timestamp >= cutoff",
                [],
            ),
            (
                "other tables are not checked",
                "SELECT count() FROM persons WHERE properties.email = 'x'",
                [],
            ),
            (
                # Measured on a large team: `SELECT * FROM events LIMIT 101` reads about 1.7 GiB,
                # because every stream reads a granule of every column before it can stop.
                "a row limit caps the result, not the read",
                "SELECT * FROM events LIMIT 100",
                [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "an ON condition does not filter the side a LEFT JOIN keeps",
                "SELECT count() FROM events e LEFT JOIN persons p ON e.person_id = p.id "
                "AND e.event = 'x' AND e.timestamp >= today()",
                [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "an ON condition filters the side a LEFT JOIN drops rows from",
                "SELECT count() FROM persons p LEFT JOIN events e ON e.person_id = p.id "
                "AND e.event = 'x' AND e.timestamp >= today()",
                [],
            ),
            (
                "a FULL JOIN keeps both sides whatever its ON condition says",
                "SELECT count() FROM events e FULL OUTER JOIN persons p ON e.person_id = p.id "
                "AND e.event = 'x' AND e.timestamp >= today()",
                [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "a semi join returns only matching rows, so its ON condition filters both sides",
                "SELECT count() FROM events e LEFT SEMI JOIN persons p ON e.person_id = p.id "
                "AND e.event = 'x' AND e.timestamp >= today()",
                [],
            ),
            (
                "a self-join reports the side that is not filtered",
                "SELECT count() FROM events a JOIN events b ON a.person_id = b.person_id "
                "WHERE a.event = 'x' AND a.timestamp >= today()",
                [EventsScanReason.NO_EVENT_FILTER, EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "a self-join with both sides filtered is fine",
                "SELECT count() FROM events a JOIN events b ON a.person_id = b.person_id "
                "AND b.event = 'y' AND b.timestamp >= today() WHERE a.event = 'x' AND a.timestamp >= today()",
                [],
            ),
            (
                "a property filter on one side of a self-join is not the other side's",
                "SELECT count() FROM events a JOIN events b ON a.person_id = b.person_id "
                "AND b.event = 'y' AND b.timestamp >= today() WHERE a.properties.plan = 'pro' AND a.timestamp >= today()",
                [EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT],
            ),
            (
                "a select alias carries the timestamp bound",
                "SELECT toStartOfDay(timestamp) AS day, count() FROM events "
                "WHERE day >= now() - INTERVAL 7 DAY AND event = 'a' GROUP BY day",
                [],
            ),
            (
                "a select alias carries the event name filter",
                "SELECT event AS name, count() FROM events WHERE name = 'a' AND timestamp >= today() GROUP BY name",
                [],
            ),
            (
                "an alias that is not the timestamp does not bound the read",
                "SELECT 1 AS day, count() FROM events WHERE day >= 0 AND event = 'a' GROUP BY day",
                [EventsScanReason.NO_TIME_BOUND],
            ),
            (
                "an alias that names itself does not loop",
                "SELECT event AS event, count() FROM events WHERE event = 'a' AND timestamp >= today() GROUP BY event",
                [],
            ),
        ]
    )
    def test_reasons(self, _name: str, query: str, expected: list[EventsScanReason]) -> None:
        self.assertEqual(reasons(query), expected)

    def test_aliases_that_multiply_each_other_stop_expanding(self) -> None:
        # Each reference expands on its own, so `a2 = plus(a1, a1)` doubles what `a1` expands to.
        # Expanding 40 of them in full would build a predicate of a trillion nodes.
        chain = ", ".join(["1 AS a0", *(f"plus(a{i - 1}, a{i - 1}) AS a{i}" for i in range(1, 41))])
        query = f"SELECT {chain} FROM events WHERE a40 > 0 AND event = 'a' AND timestamp >= today()"
        self.assertEqual(reasons(query), [])

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

        aliased = "SELECT properties.plan AS p, count() FROM events WHERE p = 'pro' AND timestamp >= today() GROUP BY p"
        (from_alias,) = find_events_scans(parse_select(aliased), DATABASE)
        self.assertEqual(from_alias.reason, EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT)
        self.assertEqual(from_alias.property_names, ("plan",))

    @parameterized.expand(
        [
            ("not in", "properties.$host NOT IN ('localhost')"),
            ("not equals", "properties.$host != 'localhost'"),
            ("negated equals", "NOT (properties.$host = 'localhost')"),
        ]
    )
    def test_exclusion_filters_still_warn_but_do_not_feed_the_hint(self, _name: str, predicate: str) -> None:
        query = f"SELECT count() FROM events WHERE {predicate} AND timestamp >= today()"
        (finding,) = find_events_scans(parse_select(query), DATABASE)
        self.assertEqual(finding.reason, EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT)
        self.assertEqual(finding.property_names, ())

    def test_findings_only_in_the_expanded_query_are_attributed_to_the_filters_that_added_them(self) -> None:
        as_written = find_events_scans(parse_select("SELECT count() FROM events WHERE {filters}"), DATABASE)
        with_test_accounts = find_events_scans(
            parse_select("SELECT count() FROM events WHERE properties.$host NOT IN ('x') AND timestamp >= today()"),
            DATABASE,
        )
        without_test_accounts = find_events_scans(
            parse_select("SELECT count() FROM events WHERE timestamp >= today()"), DATABASE
        )

        (from_setting,) = attribute_findings(with_test_accounts, as_written, without_test_accounts)
        self.assertEqual(from_setting.source, EventsScanSource.TEST_ACCOUNT_FILTERS)
        self.assertIn("Filter out internal and test users", finding_message(from_setting))
        self.assertIsNone(finding_fix(from_setting))

        (from_ui,) = attribute_findings(with_test_accounts, as_written, with_test_accounts)
        self.assertEqual(from_ui.source, EventsScanSource.UI_FILTERS)

        (unknown,) = attribute_findings(with_test_accounts, as_written, None)
        self.assertEqual(unknown.source, EventsScanSource.UNKNOWN)
        self.assertIn("contact PostHog support", finding_message(unknown))
        self.assertIn("contact PostHog support", finding_message(unknown))

        # The user's own finding keeps its hint properties and the plain advice
        own = find_events_scans(
            parse_select("SELECT count() FROM events WHERE properties.plan = 'a' AND {filters}"), DATABASE
        )
        (kept,) = attribute_findings(own, own, own)
        self.assertEqual((kept.source, kept.property_names), (EventsScanSource.QUERY, ("plan",)))
