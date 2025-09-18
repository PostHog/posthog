from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest import TestCase

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.schema import (
    DateRange,
    ErrorTrackingIssueFilter,
    ErrorTrackingQuery,
    FilterLogicalOperator,
    PersonPropertyFilter,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner, search_tokenizer
from posthog.models.error_tracking import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    override_error_tracking_issue_fingerprint,
    update_error_tracking_issue_fingerprints,
)
from posthog.models.utils import uuid7

from ee.models.rbac.role import Role


class TestErrorTrackingQueryRunner(ClickhouseTestMixin, APIBaseTest):
    distinct_id_one = "user_1"
    distinct_id_two = "user_2"
    issue_name_one = "TypeError"
    issue_name_two = "ReferenceError"
    issue_id_one = "01936e7f-d7ff-7314-b2d4-7627981e34f0"
    issue_id_two = "01936e80-5e69-7e70-b837-871f5cdad28b"
    issue_id_three = "01936e80-aa51-746f-aec4-cdf16a5c5332"
    issue_three_fingerprint = "issue_three_fingerprint"

    def override_fingerprint(self, fingerprint, issue_id, version=1):
        update_error_tracking_issue_fingerprints(team_id=self.team.pk, issue_id=issue_id, fingerprints=[fingerprint])
        override_error_tracking_issue_fingerprint(
            team_id=self.team.pk, fingerprint=fingerprint, issue_id=issue_id, version=version
        )

    def create_issue(self, issue_id, fingerprint, name=None, status=ErrorTrackingIssue.Status.ACTIVE):
        issue = ErrorTrackingIssue.objects.create(id=issue_id, team=self.team, status=status, name=name)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)

        return issue

    def create_events_and_issue(
        self,
        issue_id,
        fingerprint,
        distinct_ids,
        timestamp=None,
        exception_list=None,
        additional_properties=None,
        issue_name=None,
    ):
        if timestamp:
            with freeze_time(timestamp):
                self.create_issue(issue_id, fingerprint, name=issue_name)
        else:
            self.create_issue(issue_id, fingerprint, name=issue_name)

        event_properties = {"$exception_issue_id": issue_id, "$exception_fingerprint": fingerprint}
        if exception_list:
            event_properties["$exception_list"] = exception_list

        for distinct_id in distinct_ids:
            _create_event(
                distinct_id=distinct_id,
                event="$exception",
                team=self.team,
                properties={**event_properties, **additional_properties} if additional_properties else event_properties,
                timestamp=timestamp,
            )

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

            self.create_events_and_issue(
                issue_id=self.issue_id_one,
                issue_name=self.issue_name_one,
                fingerprint="issue_one_fingerprint",
                distinct_ids=[self.distinct_id_one, self.distinct_id_two],
                timestamp=now() - relativedelta(hours=3),
            )
            self.create_events_and_issue(
                issue_id=self.issue_id_two,
                issue_name=self.issue_name_two,
                fingerprint="issue_two_fingerprint",
                distinct_ids=[self.distinct_id_one],
                timestamp=now() - relativedelta(hours=2),
            )
            self.create_events_and_issue(
                issue_id=self.issue_id_three,
                fingerprint=self.issue_three_fingerprint,
                distinct_ids=[self.distinct_id_two],
                timestamp=now() - relativedelta(hours=1),
            )

        flush_persons_and_events()

    def _calculate(
        self,
        dateRange=None,
        assignee=None,
        issueId=None,
        filterTestAccounts=False,
        searchQuery=None,
        filterGroup=None,
        orderBy=None,
        status=None,
        volumeResolution=1,
        withAggregations=False,
        withFirstEvent=False,
    ):
        return (
            ErrorTrackingQueryRunner(
                team=self.team,
                query=ErrorTrackingQuery(
                    kind="ErrorTrackingQuery",
                    dateRange=DateRange() if dateRange is None else dateRange,
                    assignee=assignee,
                    issueId=issueId,
                    filterTestAccounts=filterTestAccounts,
                    searchQuery=searchQuery,
                    filterGroup=filterGroup,
                    orderBy=orderBy,
                    status=status,
                    volumeResolution=volumeResolution,
                    withFirstEvent=withFirstEvent,
                    withAggregations=withAggregations,
                ),
            )
            .calculate()
            .model_dump()
        )

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_column_names(self):
        columns = self._calculate()["columns"]
        self.assertEqual(
            columns,
            [
                "id",
                "last_seen",
                "first_seen",
                "library",
            ],
        )

        columns = self._calculate(withAggregations=True)["columns"]
        self.assertEqual(
            columns,
            [
                "id",
                "last_seen",
                "first_seen",
                "occurrences",
                "sessions",
                "users",
                "volumeRange",
                "library",
            ],
        )

        columns = self._calculate(withFirstEvent=True)["columns"]
        self.assertEqual(
            columns,
            [
                "id",
                "last_seen",
                "first_seen",
                "first_event",
                "library",
            ],
        )

        columns = self._calculate(issueId=self.issue_id_one, withAggregations=True, withFirstEvent=True)["columns"]
        self.assertEqual(
            columns,
            [
                "id",
                "last_seen",
                "first_seen",
                "occurrences",
                "sessions",
                "users",
                "volumeRange",
                "first_event",
                "library",
            ],
        )

    @freeze_time("2022-01-10T12:11:00")
    def test_date_range_resolution(self):
        date_from = ErrorTrackingQueryRunner.parse_relative_date_from("-1d")
        date_to = ErrorTrackingQueryRunner.parse_relative_date_to("+1d")
        self.assertEqual(date_from, datetime(2022, 1, 9, 12, 11, 0, tzinfo=ZoneInfo(key="UTC")))
        self.assertEqual(date_to, datetime(2022, 1, 11, 12, 11, 0, tzinfo=ZoneInfo(key="UTC")))

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_issue_grouping(self):
        results = self._calculate(issueId=self.issue_id_one, withAggregations=True)["results"]
        # returns a single group with multiple errors
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.issue_id_one)
        self.assertEqual(results[0]["aggregations"]["occurrences"], 2)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_search_query(self):
        self.create_events_and_issue(
            issue_id="01936e81-b0ce-7b56-8497-791e505b0d0c",
            fingerprint="fingerprint_DatabaseNotFoundX",
            distinct_ids=[self.distinct_id_one],
            exception_list=[{"type": "DatabaseNotFoundX", "value": "this is the same error message"}],
            additional_properties={"$exception_types": "['DatabaseNotFoundX']"},
        )
        self.create_events_and_issue(
            issue_id="01936e81-f5ce-79b1-99f1-f0e9675fcfef",
            fingerprint="fingerprint_DatabaseNotFoundY",
            distinct_ids=[self.distinct_id_one],
            exception_list=[{"type": "DatabaseNotFoundY", "value": "this is the same error message"}],
            additional_properties={"$exception_types": "['DatabaseNotFoundY']"},
        )
        self.create_events_and_issue(
            issue_id="01936e82-241e-7e27-b47d-6659c54eb0be",
            fingerprint="fingerprint_xyz",
            distinct_ids=[self.distinct_id_two],
            exception_list=[{"type": "xyz", "value": "this is the same error message"}],
            additional_properties={"$exception_types": "['xyz']"},
        )
        flush_persons_and_events()

        results = sorted(
            self._calculate(
                dateRange=DateRange(date_from="-1d", date_to="+1d"),
                filterTestAccounts=True,
                searchQuery="databasenot",
                withAggregations=True,
            )["results"],
            key=lambda x: x["id"],
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "01936e81-b0ce-7b56-8497-791e505b0d0c")
        self.assertEqual(results[0]["aggregations"]["occurrences"], 1)
        self.assertEqual(results[0]["aggregations"]["sessions"], 0)
        self.assertEqual(results[0]["aggregations"]["users"], 1)

        self.assertEqual(results[1]["id"], "01936e81-f5ce-79b1-99f1-f0e9675fcfef")
        self.assertEqual(results[1]["aggregations"]["occurrences"], 1)
        self.assertEqual(results[1]["aggregations"]["sessions"], 0)
        self.assertEqual(results[1]["aggregations"]["users"], 1)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_empty_search_query(self):
        results = self._calculate(searchQuery="probs not found")["results"]
        self.assertEqual(len(results), 0)

    @freeze_time("2022-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_search_query_with_multiple_search_items(self):
        self.create_events_and_issue(
            issue_id="01936e81-b0ce-7b56-8497-791e505b0d0c",
            fingerprint="fingerprint_DatabaseNotFoundX",
            distinct_ids=[self.distinct_id_one],
            additional_properties={
                "$exception_types": "['DatabaseNotFoundX']",
                "$exception_values": "['this is the same error message']",
                "$exception_sources": "['posthog/clickhouse/client/execute.py']",
            },
        )

        self.create_events_and_issue(
            issue_id="01936e81-f5ce-79b1-99f1-f0e9675fcfef",
            fingerprint="fingerprint_DatabaseNotFoundY",
            distinct_ids=[self.distinct_id_two],
            additional_properties={
                "$exception_types": "['DatabaseNotFoundY']",
                "$exception_values": "['this is the same error message']",
                "$exception_sources": "['posthog/clickhouse/client/execute.py']",
            },
        )
        flush_persons_and_events()

        results = self._calculate(
            filterTestAccounts=True, searchQuery="databasenotfoundX clickhouse/client/execute.py", withAggregations=True
        )["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "01936e81-b0ce-7b56-8497-791e505b0d0c")
        self.assertEqual(results[0]["aggregations"]["occurrences"], 1)
        self.assertEqual(results[0]["aggregations"]["sessions"], 0)
        self.assertEqual(results[0]["aggregations"]["users"], 1)

    @freeze_time("2022-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_search_person_properties(self):
        distinct_id = "david@posthog.com"

        _create_person(
            team=self.team,
            distinct_ids=[distinct_id],
            properties={"email": distinct_id},
            is_identified=True,
        )

        self.create_events_and_issue(
            issue_id="684bd8ae-498f-4548-bc05-e621b5b5b9aa",
            fingerprint="fingerprint_DatabaseNotFoundX",
            distinct_ids=[distinct_id],
        )

        results = self._calculate(searchQuery="david@posthog.com")["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "684bd8ae-498f-4548-bc05-e621b5b5b9aa")

    @freeze_time("2020-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_only_returns_exception_events(self):
        _create_event(
            distinct_id=self.distinct_id_one,
            event="$pageview",
            team=self.team,
            properties={"$exception_issue_id": self.issue_id_one},
        )
        flush_persons_and_events()

        results = self._calculate()["results"]
        self.assertEqual(len(results), 3)

    @freeze_time("2022-01-10 12:11:00")
    @snapshot_clickhouse_queries
    def test_correctly_counts_session_ids(self):
        _create_event(
            distinct_id=self.distinct_id_one,
            event="$exception",
            team=self.team,
            properties={"$session_id": str(uuid7()), "$exception_issue_id": self.issue_id_one},
        )
        _create_event(
            distinct_id=self.distinct_id_one,
            event="$exception",
            team=self.team,
            properties={"$session_id": str(uuid7()), "$exception_issue_id": self.issue_id_one},
        )
        # blank string
        _create_event(
            distinct_id=self.distinct_id_one,
            event="$exception",
            team=self.team,
            properties={"$session_id": "", "$exception_issue_id": self.issue_id_one},
        )
        flush_persons_and_events()

        results = self._calculate(issueId=self.issue_id_one, withAggregations=True)["results"]
        self.assertEqual(results[0]["id"], self.issue_id_one)
        # only includes valid session ids
        self.assertEqual(results[0]["aggregations"]["sessions"], 2)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_hogql_filters(self):
        results = self._calculate(
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
            )
        )["results"]
        # two errors exist for person with distinct_id_two
        self.assertEqual(len(results), 2)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_ordering(self):
        results = self._calculate(orderBy="last_seen")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two, self.issue_id_one])

        results = self._calculate(orderBy="first_seen")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_one, self.issue_id_two, self.issue_id_three])

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_status(self):
        resolved_issue = ErrorTrackingIssue.objects.get(id=self.issue_id_one)
        resolved_issue.status = ErrorTrackingIssue.Status.RESOLVED
        resolved_issue.save()

        results = self._calculate(status="active")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two])

        results = self._calculate(status="resolved")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_one])

        results = self._calculate()["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_one, self.issue_id_two])

        results = self._calculate(status="all")["results"]
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_one, self.issue_id_two])

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_overrides_aggregation(self):
        self.override_fingerprint(self.issue_three_fingerprint, self.issue_id_one)
        results = self._calculate(withAggregations=True, orderBy="occurrences")["results"]
        self.assertEqual(len(results), 2)

        # count is (2 x issue_one) + (1 x issue_three)
        self.assertEqual(results[0]["id"], self.issue_id_one)
        self.assertEqual(results[0]["aggregations"]["occurrences"], 3)

        self.assertEqual(results[1]["id"], self.issue_id_two)
        self.assertEqual(results[1]["aggregations"]["occurrences"], 1)

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_user_assignee(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-107034368d64"
        self.create_events_and_issue(
            issue_id=issue_id,
            fingerprint="assigned_issue_fingerprint",
            distinct_ids=[self.distinct_id_one],
        )
        flush_persons_and_events()
        ErrorTrackingIssueAssignment.objects.create(issue_id=issue_id, user=self.user)

        results = self._calculate(assignee={"type": "user", "id": self.user.pk})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_role_assignee(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-107034368d64"
        self.create_events_and_issue(
            issue_id=issue_id,
            fingerprint="assigned_issue_fingerprint",
            distinct_ids=[self.distinct_id_one],
        )
        flush_persons_and_events()
        role = Role.objects.create(name="Test Team", organization=self.organization)
        ErrorTrackingIssueAssignment.objects.create(issue_id=issue_id, role=role)

        results = self._calculate(assignee={"type": "role", "id": str(role.id)})["results"]
        self.assertEqual([x["id"] for x in results], [issue_id])

    @freeze_time("2022-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_issue_filters(self):
        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="name", value=[self.issue_name_one], operator=PropertyOperator.EXACT
                            ),
                        ],
                    )
                ],
            )
        )["results"]
        self.assertEqual(len(results), 1)

    @freeze_time("2020-01-10T12:11:00")
    @snapshot_clickhouse_queries
    def test_first_seen_filters(self):
        cutoff_time = now() - relativedelta(hours=2)

        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="first_seen", value=cutoff_time.isoformat(), operator=PropertyOperator.GTE
                            ),
                        ],
                    )
                ],
            )
        )["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual([r["id"] for r in results], [self.issue_id_three, self.issue_id_two])

        results = self._calculate(
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            ErrorTrackingIssueFilter(
                                key="first_seen", value=cutoff_time.isoformat(), operator=PropertyOperator.LT
                            ),
                        ],
                    )
                ],
            )
        )["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual([r["id"] for r in results], [self.issue_id_one])

    @freeze_time("2020-01-12")
    @snapshot_clickhouse_queries
    def test_volume_aggregation_simple(self):
        results = self._calculate(
            volumeResolution=3, dateRange=DateRange(date_from="2020-01-10", date_to="2020-01-11"), withAggregations=True
        )["results"]
        self.assertEqual(len(results), 3)

        ## Make sure resolution is correct
        for result in results:
            aggregations = result["aggregations"]
            self.assertEqual(len(aggregations["volumeRange"]), 3)

        ## Make sure occurrences are correct
        first_aggregations = results[0]["aggregations"]
        self.assertEqual(first_aggregations["volumeRange"], [0, 1, 0])

    @freeze_time("2025-05-05")
    @snapshot_clickhouse_queries
    def test_volume_aggregation_advanced(self):
        issue_id = "e9ac529f-ac1c-4a96-bd3a-102334368d64"
        issue_fingerprint = "fingerprint"
        self.create_issue(issue_id, issue_fingerprint)
        for ts in range(0, 24):
            event_properties = {
                "$exception_issue_id": issue_id,
                "$exception_fingerprint": issue_fingerprint,
                "$exception_list": [],
            }
            for distinct_id in range(0, 5):
                event_ts = now() - timedelta(hours=ts)
                _create_event(
                    distinct_id=f"{issue_id}_{ts}_{distinct_id}",
                    event="$exception",
                    team=self.team,
                    properties=event_properties,
                    timestamp=event_ts,
                )
        flush_persons_and_events()

        results = self._calculate(
            volumeResolution=4,
            issueId=issue_id,
            dateRange=DateRange(date_from="2025-05-04", date_to="2025-05-06"),
            withAggregations=True,
        )["results"]
        self.assertEqual(len(results), 1)

        ## Make sure resolution is correct
        for result in results:
            aggregations = result["aggregations"]
            self.assertEqual(len(aggregations["volumeRange"]), 4)

        ## Make sure occurrences are correct
        first_aggregations = results[0]["aggregations"]
        self.assertEqual(sum(first_aggregations["volumeRange"]), 24 * 5)
        self.assertEqual(first_aggregations["volumeRange"], [60, 60, 0, 0])


class TestSearchTokenizer(TestCase):
    test_cases = [
        (
            "This is a \"quoted string\" and this is 'another one' with some words",
            ["This", "is", "a", "quoted string", "and", "this", "is", "another one", "with", "some", "words"],
        ),
        (
            "Empty quotes: \"\" and '' should be preserved",
            ["Empty", "quotes:", "", "and", "", "should", "be", "preserved"],
        ),
        ("Nested \"quotes 'are' tricky\" to handle", ["Nested", "quotes 'are' tricky", "to", "handle"]),
        (
            "Unmatched quotes: \"open quote and 'partial quote",
            ["Unmatched", "quotes:", "open", "quote", "and", "partial", "quote"],
        ),
        ("Multiple     spaces      between words", ["Multiple", "spaces", "between", "words"]),
        (
            "Special characters: @#$% should be treated as words",
            ["Special", "characters:", "@#$%", "should", "be", "treated", "as", "words"],
        ),
        (
            "Single quotes at \"start\" and 'end' of string",
            ["Single", "quotes", "at", "start", "and", "end", "of", "string"],
        ),
        ('"Entire string is quoted"', ["Entire string is quoted"]),
        ('Escaped quotes: "He said "Hello" to me"', ["Escaped", "quotes:", "He said ", "Hello", "to", "me"]),
    ]

    def test_tokenizer(self):
        for case, output in self.test_cases:
            with self.subTest(case=case):
                tokens = search_tokenizer(case)
                self.assertEqual(tokens, output)
