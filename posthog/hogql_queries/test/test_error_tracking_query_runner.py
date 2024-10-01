from freezegun import freeze_time

from posthog.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner
from posthog.schema import (
    ErrorTrackingQuery,
    DateRange,
    FilterLogicalOperator,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PersonPropertyFilter,
    PropertyOperator,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
    _create_person,
    _create_event,
    flush_persons_and_events,
)
from posthog.models import ErrorTrackingGroup
from datetime import datetime
from zoneinfo import ZoneInfo


class TestErrorTrackingQueryRunner(ClickhouseTestMixin, APIBaseTest):
    distinct_id_one = "user_1"
    distinct_id_two = "user_2"

    def setUp(self):
        super().setUp()

        with freeze_time("2020-01-10 12:11:00"):
            _create_person(
                team=self.team,
                distinct_ids=[self.distinct_id_one],
                is_identified=True,
            )
            _create_person(
                team=self.team,
                properties={
                    "email": "email@posthog.com",
                    "name": "Test User",
                },
                distinct_ids=[self.distinct_id_two],
                is_identified=True,
            )

            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["SyntaxError"],
                    "$exception_type": "SyntaxError",
                    "$exception_message": "this is the same error message",
                },
            )
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["TypeError"],
                    "$exception_type": "TypeError",
                },
            )
            _create_event(
                distinct_id=self.distinct_id_two,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["SyntaxError"],
                    "$exception_type": "SyntaxError",
                    "$exception_message": "this is the same error message",
                },
            )
            _create_event(
                distinct_id=self.distinct_id_two,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["custom_fingerprint"],
                    "$exception_type": "SyntaxError",
                    "$exception_message": "this is the same error message",
                },
            )

        flush_persons_and_events()

    def _calculate(self, runner: ErrorTrackingQueryRunner):
        return runner.calculate().model_dump()

    @snapshot_clickhouse_queries
    def test_column_names(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=None,
                dateRange=DateRange(),
                filterTestAccounts=True,
            ),
        )

        columns = self._calculate(runner)["columns"]
        self.assertEqual(
            columns,
            [
                "occurrences",
                "sessions",
                "users",
                "last_seen",
                "first_seen",
                "description",
                "exception_type",
                "fingerprint",
            ],
        )

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=["SyntaxError"],
                dateRange=DateRange(),
                filterTestAccounts=True,
            ),
        )

        columns = self._calculate(runner)["columns"]
        self.assertEqual(
            columns,
            [
                "occurrences",
                "sessions",
                "users",
                "last_seen",
                "first_seen",
                "description",
                "exception_type",
            ],
        )

    @snapshot_clickhouse_queries
    def test_search_query(self):
        with freeze_time("2022-01-10 12:11:00"):
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["DatabaseNotFoundX"],
                    "$exception_type": "DatabaseNotFoundX",
                    "$exception_message": "this is the same error message",
                },
            )
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["DatabaseNotFoundY"],
                    "$exception_type": "DatabaseNotFoundY",
                    "$exception_message": "this is the same error message",
                },
            )
            _create_event(
                distinct_id=self.distinct_id_two,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["xyz"],
                    "$exception_type": "xyz",
                    "$exception_message": "this is the same error message",
                },
            )
            flush_persons_and_events()

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=None,
                dateRange=DateRange(date_from="2022-01-10", date_to="2022-01-11"),
                filterTestAccounts=True,
                searchQuery="databasenot",
            ),
        )

        results = sorted(self._calculate(runner)["results"], key=lambda x: x["fingerprint"])

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["fingerprint"], ["DatabaseNotFoundX"])
        self.assertEqual(results[0]["occurrences"], 1)
        self.assertEqual(results[0]["sessions"], 1)
        self.assertEqual(results[0]["users"], 1)

        self.assertEqual(results[1]["fingerprint"], ["DatabaseNotFoundY"])
        self.assertEqual(results[1]["occurrences"], 1)
        self.assertEqual(results[1]["sessions"], 1)
        self.assertEqual(results[1]["users"], 1)

    def test_empty_search_query(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=None,
                dateRange=DateRange(),
                filterTestAccounts=False,
                searchQuery="probs not found",
            ),
        )

        results = self._calculate(runner)["results"]

        self.assertEqual(len(results), 0)

    @snapshot_clickhouse_queries
    def test_fingerprints(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=["SyntaxError"],
                dateRange=DateRange(),
            ),
        )

        results = self._calculate(runner)["results"]
        # returns a single group with multiple errors
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["fingerprint"], ["SyntaxError"])
        self.assertEqual(results[0]["occurrences"], 2)

    def test_only_returns_exception_events(self):
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$pageview",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["SyntaxError"],
                },
            )
        flush_persons_and_events()

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
            ),
        )

        results = self._calculate(runner)["results"]
        self.assertEqual(len(results), 3)

    @snapshot_clickhouse_queries
    def test_hogql_filters(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                filterGroup=PropertyGroupFilter(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.OR_,
                            values=[
                                PersonPropertyFilter(
                                    key="email", value="email@posthog.com", operator=PropertyOperator.EXACT
                                ),
                            ],
                        )
                    ],
                ),
            ),
        )

        results = self._calculate(runner)["results"]
        # two errors exist for person with distinct_id_two
        self.assertEqual(len(results), 2)

    def test_merges_and_defaults_groups(self):
        ErrorTrackingGroup.objects.create(
            team=self.team,
            fingerprint=["SyntaxError"],
            merged_fingerprints=[["custom_fingerprint"]],
            assignee=self.user,
        )

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery", fingerprint=None, dateRange=DateRange(), order="occurrences"
            ),
        )

        results = self._calculate(runner)["results"]
        self.assertEqual(
            results,
            [
                {
                    "assignee": self.user.id,
                    "description": "this is the same error message",
                    "exception_type": "SyntaxError",
                    "fingerprint": ["SyntaxError"],
                    "first_seen": datetime(2020, 1, 10, 12, 11, tzinfo=ZoneInfo("UTC")),
                    "last_seen": datetime(2020, 1, 10, 12, 11, tzinfo=ZoneInfo("UTC")),
                    "merged_fingerprints": [["custom_fingerprint"]],
                    # count is (2 x SyntaxError) + (1 x custom_fingerprint)
                    "occurrences": 3,
                    "sessions": 1,
                    "users": 2,
                    "volume": None,
                    "status": ErrorTrackingGroup.Status.ACTIVE,
                },
                {
                    "assignee": None,
                    "description": None,
                    "exception_type": "TypeError",
                    "fingerprint": ["TypeError"],
                    "first_seen": datetime(2020, 1, 10, 12, 11, tzinfo=ZoneInfo("UTC")),
                    "last_seen": datetime(2020, 1, 10, 12, 11, tzinfo=ZoneInfo("UTC")),
                    "merged_fingerprints": [],
                    "occurrences": 1,
                    "sessions": 1,
                    "users": 1,
                    "volume": None,
                    "status": ErrorTrackingGroup.Status.ACTIVE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_assignee_groups(self):
        ErrorTrackingGroup.objects.create(
            team=self.team,
            fingerprint=["SyntaxError"],
            assignee=self.user,
        )
        ErrorTrackingGroup.objects.create(
            team=self.team,
            fingerprint=["custom_fingerprint"],
            assignee=self.user,
        )
        ErrorTrackingGroup.objects.create(
            team=self.team,
            fingerprint=["TypeError"],
        )

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                assignee=self.user.pk,
            ),
        )

        results = self._calculate(runner)["results"]

        self.assertEqual(sorted([x["fingerprint"] for x in results]), [["SyntaxError"], ["custom_fingerprint"]])
