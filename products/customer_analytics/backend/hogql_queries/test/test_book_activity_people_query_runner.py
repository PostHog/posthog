from typing import Any
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError

from posthog.schema import BookActivityMatrixEmptyReason, BookActivityMatrixQuery, BookActivityPeopleQuery

from products.customer_analytics.backend.hogql_queries import (
    book_activity_base,
    book_activity_people_query_runner as people_module,
)
from products.customer_analytics.backend.hogql_queries.book_activity_matrix_query_runner import (
    BookActivityMatrixQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.book_activity_people_query_runner import (
    BookActivityPeopleQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.test.book_activity_test_case import (
    ANA,
    BO,
    CY,
    DEE,
    EVE,
    BookActivityTestCase,
)
from products.customer_analytics.backend.test.factories import create_account

THIS_WEEK = "2026-10-25"
LAST_WEEK = "2026-10-18"


@time_machine.travel("2026-10-28T18:00:00Z", tick=False)
class TestBookActivityPeopleQueryRunner(BookActivityTestCase):
    def _query(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "BookActivityPeopleQuery",
            "accountIds": [str(self.alpha.id), str(self.beta.id)],
            "dateRange": {"date_from": "-4w"},
            "interval": "week",
            **kwargs,
        }

    def _run(self, **kwargs: Any) -> Any:
        flush_persons_and_events()
        query = BookActivityPeopleQuery(**self._query(**kwargs))
        return BookActivityPeopleQueryRunner(team=self.team, query=query, user=self.user).calculate().results

    @parameterized.expand(
        [
            ("product event", "insight created", {}, 0, 1),
            (
                "30 seconds on a product page",
                "$pageview",
                {"$prev_pageview_pathname": "/project/1/insights/a", "$prev_pageview_duration": 30},
                30,
                0,
            ),
            (
                "30 minutes on a product page",
                "$pageleave",
                {"$prev_pageview_pathname": "/project/1/insights/a", "$prev_pageview_duration": 1800},
                1800,
                0,
            ),
        ]
    )
    def test_qualifies_a_person(
        self, _name: str, event: str, properties: dict[str, Any], engaged: int, actions: int
    ) -> None:
        self._event(ANA, event, "2026-10-26T10:00:00Z", self.alpha, properties=properties)

        people = self._run().people

        assert [(p.row, p.column, p.series, p.personId, p.engagedSeconds, p.actionCount) for p in people] == [
            (str(self.alpha.id), THIS_WEEK, "pa", ANA, engaged, actions)
        ]

    @parameterized.expand(
        [
            (
                "10 seconds on a product page",
                "$pageview",
                {"$prev_pageview_pathname": "/project/1/insights/a", "$prev_pageview_duration": 10},
            ),
            (
                "2 hours on a product page",
                "$pageview",
                {"$prev_pageview_pathname": "/project/1/insights/a", "$prev_pageview_duration": 7200},
            ),
            (
                "a page no product claims",
                "$pageview",
                {"$prev_pageview_pathname": "/project/1/settings/a", "$prev_pageview_duration": 60},
            ),
            ("an event no product claims", "unrelated event", {}),
            ("too little replay", "recording viewed summary", {"play_time_ms": 9999}),
        ]
    )
    def test_does_not_qualify_a_person(self, _name: str, event: str, properties: dict[str, Any]) -> None:
        self._event(ANA, event, "2026-10-26T10:00:00Z", self.alpha, properties=properties)

        assert self._run().people == []

    def test_counts_enough_replay_as_a_replay_action(self) -> None:
        self._event(ANA, "recording viewed summary", "2026-10-26T10:00:00Z", self.alpha, {"play_time_ms": 10000})

        people = self._run().people

        assert [(p.series, p.actionCount, [(a.event, a.count) for a in p.actions]) for p in people] == [
            ("replay", 1, [("recording viewed summary", 1)])
        ]

    def test_returns_what_qualified_the_person(self) -> None:
        for _ in range(3):
            self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        self._event(ANA, "dashboard updated", "2026-10-26T10:00:00Z", self.alpha)
        for path, seconds in (
            ("/project/1/insights/new", 300),
            ("/project/2/insights/new", 70),  # The same page in another project.
            ("/project/1/dashboard/42", 245),
            ("/project/1/insights/aB3xQ9", 171),
            ("/project/1/persons/1", 90),
            ("/project/1/cohorts/1", 80),
            ("/project/1/events", 31),
        ):
            self._dwell(ANA, seconds, "2026-10-26T11:00:00Z", self.alpha, path=path)

        person = self._run().people[0]

        assert (person.engagedSeconds, person.actionCount) == (987, 4)
        assert [(a.event, a.count) for a in person.actions] == [("insight created", 3), ("dashboard updated", 1)]
        assert [(p.path, p.seconds) for p in person.topPaths] == [
            ("/insights/new", 370),
            ("/dashboard/42", 245),
            ("/insights/aB3xQ9", 171),
            ("/persons/1", 90),
            ("/cohorts/1", 80),
        ]

    def test_keeps_each_bucket_and_product_apart(self) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        self._event(ANA, "insight created", "2026-10-27T10:00:00Z", self.alpha)
        self._event(ANA, "insight created", "2026-10-20T10:00:00Z", self.alpha)
        self._event(ANA, "feature flag created", "2026-10-26T10:00:00Z", self.alpha)
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.beta)

        people = self._run().people

        alpha, beta = str(self.alpha.id), str(self.beta.id)
        assert [(p.row, p.series, p.column, p.actionCount) for p in people] == [
            (alpha, "flags", THIS_WEEK, 1),
            (alpha, "pa", LAST_WEEK, 1),
            (alpha, "pa", THIS_WEEK, 2),
            (beta, "pa", THIS_WEEK, 1),
        ]

    def test_ranks_by_engaged_seconds_plus_actions_within_each_cell(self) -> None:
        self._dwell(ANA, 40, "2026-10-26T10:00:00Z", self.alpha)  # 40
        self._dwell(BO, 31, "2026-10-26T10:00:00Z", self.alpha)  # 31 + 12 = 43
        for _ in range(12):
            self._event(BO, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        for _ in range(10):
            self._event(CY, "insight created", "2026-10-26T10:00:00Z", self.alpha)  # 10
        self._event(CY, "insight created", "2026-10-20T10:00:00Z", self.alpha)
        self._event(CY, "insight created", "2026-10-26T10:00:00Z", self.beta)

        people = self._run(peopleLimit=2).people

        alpha, beta = str(self.alpha.id), str(self.beta.id)
        assert [(p.row, p.column, p.personId, p.rank) for p in people] == [
            (alpha, LAST_WEEK, CY, 1),
            (alpha, THIS_WEEK, BO, 1),
            (alpha, THIS_WEEK, ANA, 2),
            (beta, THIS_WEEK, CY, 1),
        ]

    def test_defaults_to_3_people_per_cell_without_calling_it_truncated(self) -> None:
        for person in (ANA, BO, CY, DEE):
            self._event(person, "insight created", "2026-10-26T10:00:00Z", self.alpha)

        results = self._run()

        assert [person.personId for person in results.people] == [ANA, BO, CY]
        assert results.truncated is False

    def test_returns_everyone_for_one_account_and_product(self) -> None:
        for person in (ANA, BO, CY, DEE, EVE):
            self._event(person, "insight created", "2026-10-26T10:00:00Z", self.alpha)
            self._event(person, "insight created", "2026-10-20T10:00:00Z", self.alpha)
        self._event(ANA, "feature flag created", "2026-10-26T10:00:00Z", self.alpha)
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.beta)

        results = self._run(accountIds=[str(self.alpha.id)], productKeys=["pa"], allPeople=True, peopleLimit=1)

        assert {(p.row, p.series) for p in results.people} == {(str(self.alpha.id), "pa")}
        assert [(p.column, p.rank) for p in results.people] == [
            *((LAST_WEEK, rank) for rank in range(1, 6)),
            *((THIS_WEEK, rank) for rank in range(1, 6)),
        ]
        assert results.truncated is False

    def test_no_cap_refuses_more_than_one_account_or_product(self) -> None:
        alpha, beta = str(self.alpha.id), str(self.beta.id)
        for kwargs in (
            {"accountIds": [alpha, beta], "productKeys": ["pa"]},
            {"accountIds": [alpha], "productKeys": ["pa", "flags"]},
            {"accountIds": [alpha]},
            {"accountIds": None, "relationshipDefinitionId": str(uuid4()), "productKeys": ["pa"]},
        ):
            with pytest.raises(ValidationError):
                self._run(allPeople=True, **kwargs)

    def test_counts_the_same_people_as_the_matrix(self) -> None:
        for person in (ANA, BO, CY, DEE, EVE):
            self._event(person, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        self._dwell(ANA, 45, "2026-10-26T10:00:00Z", self.alpha)
        self._dwell(ANA, 5, "2026-10-26T10:00:00Z", self.alpha, path="/project/1/feature_flags/1")
        self._dwell(BO, 45, "2026-10-26T10:00:00Z", self.alpha, path="/project/1/feature_flags/1")

        people = self._run(accountIds=[str(self.alpha.id)], productKeys=["pa"], allPeople=True).people
        flags = self._run(accountIds=[str(self.alpha.id)], productKeys=["flags"], allPeople=True).people
        matrix = (
            BookActivityMatrixQueryRunner(
                team=self.team,
                query=BookActivityMatrixQuery(
                    kind="BookActivityMatrixQuery",
                    accountIds=[str(self.alpha.id)],
                    dateRange={"date_from": "-4w"},
                    interval="week",
                ),
                user=self.user,
            )
            .calculate()
            .results
        )

        assert {cell.series: cell.users for cell in matrix.data} == {"pa": len(people), "flags": len(flags)}

    @parameterized.expand([(0,), (51,)])
    def test_refuses_a_people_limit_out_of_range(self, limit: int) -> None:
        with pytest.raises(PydanticValidationError):
            BookActivityPeopleQuery(**self._query(peopleLimit=limit))

    @parameterized.expand(
        [
            ("email first", {"email": "ana@acme.example", "name": "Ana"}, "ana@acme.example"),
            ("then name", {"name": "Ana Lee"}, "Ana Lee"),
            ("an empty email", {"email": "", "name": "Ana Lee"}, "Ana Lee"),
            ("then a short ID", {}, "User 11111111"),
        ]
    )
    def test_labels_a_person_without_exposing_more(
        self, _name: str, person_properties: dict[str, str], label: str
    ) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha, person_properties=person_properties)

        person = self._run().people[0]

        assert person.label == label
        assert set(person.model_dump()) == {
            "row",
            "column",
            "series",
            "personId",
            "label",
            "rank",
            "engagedSeconds",
            "actionCount",
            "actions",
            "topPaths",
        }

    def test_limits_to_the_chosen_products(self) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        self._event(ANA, "feature flag created", "2026-10-26T10:00:00Z", self.alpha)
        self._dwell(BO, 45, "2026-10-26T10:00:00Z", self.alpha, path="/project/1/feature_flags/1")
        self._dwell(CY, 45, "2026-10-26T10:00:00Z", self.alpha)
        self._event(DEE, "recording viewed summary", "2026-10-26T10:00:00Z", self.alpha, {"play_time_ms": 10000})

        people = self._run(productKeys=["flags", "replay"]).people

        assert {(p.series, p.personId) for p in people} == {("flags", ANA), ("flags", BO), ("replay", DEE)}

    def test_refuses_an_unknown_product(self) -> None:
        with pytest.raises(ValidationError):
            self._run(productKeys=["pa", "nope"])

    @parameterized.expand([("at the cap", 4, False), ("over the cap", 3, True)])
    def test_flags_a_result_cut_by_the_row_cap(self, _name: str, cap: int, truncated: bool) -> None:
        for person in (ANA, BO):
            self._event(person, "insight created", "2026-10-26T10:00:00Z", self.alpha)
            self._event(person, "insight created", "2026-10-26T10:00:00Z", self.beta)

        with patch.object(people_module, "MAX_PEOPLE_ROWS", cap):
            results = self._run()

        assert len(results.people) == cap
        assert results.truncated is truncated

    def test_flags_accounts_dropped_past_the_limits(self) -> None:
        extra = create_account(team_id=self.team.id, name="Zeta", external_id="org-z")
        ids = [str(self.alpha.id), str(self.beta.id), str(extra.id)]

        assert self._run(accountIds=ids, rowLimit=2).truncated is True
        assert self._run(accountIds=ids, rowLimit=3).truncated is False
        over = [*ids, *(str(uuid4()) for _ in range(book_activity_base.MAX_ACCOUNT_IDS))]
        assert self._run(accountIds=over, rowLimit=200).truncated is True

    def test_returns_the_rows_and_columns_it_covers(self) -> None:
        results = self._run()

        assert [row.key for row in results.rows] == [str(self.alpha.id), str(self.beta.id)]
        assert (results.columns[-1].key, results.columns[-1].partial) == (THIS_WEEK, True)
        assert results.emptyReason is None

    def test_explains_an_empty_result(self) -> None:
        assert self._run(accountIds=[]).emptyReason == BookActivityMatrixEmptyReason.EMPTY_BOOK

        self.team.customer_analytics_config.account_group_type_index = None

        assert self._run().emptyReason == BookActivityMatrixEmptyReason.NO_GROUP_TYPE

    def test_caps_daily_ranges(self) -> None:
        with pytest.raises(ValidationError):
            self._run(interval="day", dateRange={"date_from": "-6m"})

    def test_ignores_events_outside_the_range(self) -> None:
        self._event(ANA, "insight created", "2026-08-03T10:00:00Z", self.alpha)

        assert self._run().people == []

    def test_buckets_by_day_and_month(self) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)

        assert [p.column for p in self._run(interval="day", dateRange={"date_from": "-7d"}).people] == ["2026-10-26"]
        assert [p.column for p in self._run(interval="month", dateRange={"date_from": "-1m"}).people] == ["2026-10-01"]
