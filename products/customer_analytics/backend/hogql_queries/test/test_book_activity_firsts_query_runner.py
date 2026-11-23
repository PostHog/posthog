from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import BookActivityFirstsQuery, BookActivityMatrixEmptyReason

from posthog.hogql.query import execute_hogql_query

from products.customer_analytics.backend.hogql_queries import book_activity_firsts_query_runner as firsts_module
from products.customer_analytics.backend.hogql_queries.book_activity_firsts_query_runner import (
    BookActivityFirstsQueryRunner,
)
from products.customer_analytics.backend.hogql_queries.test.book_activity_test_case import (
    ANA,
    BO,
    CY,
    BookActivityTestCase,
)


@time_machine.travel("2026-10-28T18:00:00Z", tick=False)
class TestBookActivityFirstsQueryRunner(BookActivityTestCase):
    def _run(self, **kwargs: Any) -> Any:
        flush_persons_and_events()
        return (
            BookActivityFirstsQueryRunner(
                team=self.team,
                user=self.user,
                query=BookActivityFirstsQuery(
                    kind="BookActivityFirstsQuery", accountIds=[str(self.alpha.id), str(self.beta.id)], **kwargs
                ),
            )
            .calculate()
            .results
        )

    def test_returns_each_person_and_account_first_use_across_history(self) -> None:
        self._event(ANA, "insight created", "2019-03-10T10:00:00Z", self.alpha)
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        self._event(BO, "insight created", "2026-10-20T10:00:00Z", self.alpha)
        self._event(CY, "feature flag created", "2026-10-26T10:00:00Z", self.beta)
        result = self._run()
        assert {(p.row, p.series, p.personId, p.date) for p in result.people} == {
            (str(self.alpha.id), "pa", ANA, "2019-03-10"),
            (str(self.alpha.id), "pa", BO, "2026-10-20"),
            (str(self.beta.id), "flags", CY, "2026-10-26"),
        }
        assert {(p.row, p.series, p.date) for p in result.accounts} == {
            (str(self.alpha.id), "pa", "2019-03-10"),
            (str(self.beta.id), "flags", "2026-10-26"),
        }
        assert not result.truncated

    @parameterized.expand([("at cap", 3, False), ("over cap", 1, True)])
    def test_person_cap_keeps_exact_account_dates(self, _name: str, cap: int, truncated: bool) -> None:
        for person, account, date in [
            (ANA, self.alpha, "2019-03-10"),
            (BO, self.alpha, "2026-10-20"),
            (CY, self.beta, "2026-10-26"),
        ]:
            self._event(person, "insight created", date + "T10:00:00Z", account)
        with (
            patch.object(firsts_module, "MAX_FIRST_USE_ROWS", cap),
            patch(
                "products.customer_analytics.backend.hogql_queries.activity_base.execute_hogql_query",
                wraps=execute_hogql_query,
            ) as queries,
        ):
            result = self._run()
        assert queries.call_count == (2 if truncated else 1)
        assert len(result.people) == cap
        assert result.truncated == truncated
        assert {(p.row, p.date) for p in result.accounts} == {
            (str(self.alpha.id), "2019-03-10"),
            (str(self.beta.id), "2026-10-26"),
        }

    def test_excludes_staff_unqualified_events_and_other_products(self) -> None:
        self._event(
            ANA, "insight created", "2019-03-10T10:00:00Z", self.alpha, person_properties={"email": "staff@posthog.com"}
        )
        self._dwell(BO, 10, "2019-03-10T10:00:00Z", self.alpha)
        self._event(CY, "feature flag created", "2019-03-10T10:00:00Z", self.alpha)
        self._dwell(BO, 30, "2026-10-26T10:00:00Z", self.alpha)
        result = self._run(productKeys=["pa"])
        assert [(p.personId, p.date) for p in result.people] == [(BO, "2026-10-26")]
        assert [(p.series, p.date) for p in result.accounts] == [("pa", "2026-10-26")]

    def test_uses_the_team_day_at_a_timezone_boundary(self) -> None:
        self.team.timezone = "America/Los_Angeles"
        self.team.save()
        self._event(ANA, "insight created", "2026-10-26T01:00:00Z", self.alpha)
        result = self._run()
        assert [p.date for p in result.people] == ["2026-10-25"]
        assert [p.date for p in result.accounts] == ["2026-10-25"]

    def test_has_a_24_hour_cache_window(self) -> None:
        runner = BookActivityFirstsQueryRunner(
            team=self.team, user=self.user, query=BookActivityFirstsQuery(kind="BookActivityFirstsQuery", accountIds=[])
        )
        now = datetime.now(UTC)
        assert runner.cache_target_age(now) == now + timedelta(hours=24)
        assert not runner._is_stale(now - timedelta(hours=23))
        assert runner._is_stale(now - timedelta(hours=25))
        assert self._run().emptyReason is None
        self.team.customer_analytics_config.account_group_type_index = None
        assert self._run().emptyReason == BookActivityMatrixEmptyReason.NO_GROUP_TYPE
