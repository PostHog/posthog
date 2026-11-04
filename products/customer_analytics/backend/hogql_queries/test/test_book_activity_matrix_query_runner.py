from typing import Any

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.schema import BookActivityMatrixQuery, DateRange, QueryStatus

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import OrganizationMembership, User
from posthog.test.persons import create_person

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG
from products.customer_analytics.backend.hogql_queries.book_activity_matrix_query_runner import (
    BookActivityMatrixQueryRunner,
)
from products.customer_analytics.backend.models import Account
from products.customer_analytics.backend.test.factories import (
    create_account,
    create_account_relationship,
    create_account_relationship_definition,
)

ANA = "11111111-1111-4111-8111-111111111111"
BO = "22222222-2222-4222-8222-222222222222"
CY = "33333333-3333-4333-8333-333333333333"


@time_machine.travel("2026-10-28T18:00:00Z", tick=False)
class TestBookActivityMatrixQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_enabled = True
        flag_patch = patch(
            "posthog.permissions.posthoganalytics.feature_enabled",
            side_effect=lambda flag, *_args, **_kwargs: (
                self.flag_enabled and flag == CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG
            ),
        )
        self.feature_enabled = flag_patch.start()
        self.addCleanup(flag_patch.stop)
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save()
        self.tam = create_account_relationship_definition(team_id=self.team.id, name="TAM")
        csm = create_account_relationship_definition(team_id=self.team.id, name="CSM")
        self.other_user = User.objects.create_and_join(self.organization, "other@example.com", "password")
        self.alpha = create_account(team_id=self.team.id, name="Alpha", external_id="org-a")
        self.beta = create_account(team_id=self.team.id, name="Beta", external_id="org-b")
        gamma = create_account(team_id=self.team.id, name="Gamma", external_id="org-c")
        delta = create_account(team_id=self.team.id, name="Delta", external_id="org-d")
        for account, definition, user in (
            (self.alpha, self.tam, self.user),
            (self.beta, self.tam, self.user),
            (gamma, self.tam, self.other_user),
            (delta, csm, self.user),
        ):
            create_account_relationship(team_id=self.team.id, account=account, definition=definition, user=user)
        for person in (ANA, BO, CY):
            create_person(team=self.team, uuid=person, distinct_ids=[person], properties={"email": "user@example.com"})

    def _event(
        self,
        person: str,
        event: str,
        timestamp: str,
        account: Account,
        properties: dict[str, Any] | None = None,
        email: str = "user@example.com",
    ) -> None:
        _create_event(
            team=self.team,
            event=event,
            distinct_id=person,
            person_id=person,
            timestamp=timestamp,
            properties={"$group_0": account.external_id, **(properties or {})},
            person_properties={"email": email},
        )

    def _query(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "kind": "BookActivityMatrixQuery",
            "relationshipDefinitionId": str(self.tam.id),
            "userId": self.user.id,
            "dateRange": {"date_from": "-4w"},
            "interval": "week",
            **kwargs,
        }

    def _run(self, **kwargs: Any) -> Any:
        flush_persons_and_events()
        query = BookActivityMatrixQuery(**self._query(**kwargs))
        return BookActivityMatrixQueryRunner(team=self.team, query=query, user=self.user).calculate().results

    def test_counts_users_once_per_product_combination_for_the_book_only(self) -> None:
        gamma = Account.objects.for_team(self.team.id).get(external_id="org-c")
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        self._event(ANA, "feature flag created", "2026-10-27T10:00:00Z", self.alpha)
        self._event(BO, "insight created", "2026-10-26T11:00:00Z", self.alpha)
        self._event(BO, "unrelated event", "2026-10-26T12:00:00Z", self.alpha)
        self._event(CY, "survey created", "2026-10-19T10:00:00Z", self.beta)
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", gamma)

        results = self._run()

        alpha, beta = str(self.alpha.id), str(self.beta.id)
        assert [row.key for row in results.rows] == [alpha, beta]
        assert {(c.row, c.column, c.mask, c.users) for c in results.combinations} == {
            (alpha, "2026-10-25", 1 | 1 << 6, 1),
            (alpha, "2026-10-25", 1, 1),
            (beta, "2026-10-18", 1 << 4, 1),
        }
        assert {(cell.row, cell.column, cell.series, cell.users) for cell in results.data} == {
            (alpha, "2026-10-25", "pa", 2),
            (alpha, "2026-10-25", "flags", 1),
            (beta, "2026-10-18", "surveys", 1),
        }

    @parameterized.expand(
        [
            (
                "engaged page time",
                "$pageview",
                {"$prev_pageview_pathname": "/project/1/insights/a", "$prev_pageview_duration": 45},
                "user@example.com",
                True,
            ),
            (
                "a short visit",
                "$pageview",
                {"$prev_pageview_pathname": "/project/1/insights/a", "$prev_pageview_duration": 5},
                "user@example.com",
                False,
            ),
            (
                "a tab left open",
                "$pageleave",
                {"$prev_pageview_pathname": "/project/1/insights/a", "$prev_pageview_duration": 2000},
                "user@example.com",
                False,
            ),
            ("a staff member", "insight created", {}, "someone@posthog.com", False),
        ]
    )
    def test_counts_engaged_page_time_and_leaves_staff_out(
        self, _name: str, event: str, properties: dict[str, Any], email: str, counted: bool
    ) -> None:
        self._event(ANA, event, "2026-10-26T10:00:00Z", self.alpha, properties=properties, email=email)

        results = self._run()

        expected = {(str(self.alpha.id), "pa", 1)} if counted else set()
        assert {(cell.row, cell.series, cell.users) for cell in results.data} == expected

    def test_scopes_to_the_given_accounts_without_a_book(self) -> None:
        gamma = Account.objects.for_team(self.team.id).get(external_id="org-c")

        results = self._run(relationshipDefinitionId=None, userId=None, accountIds=[str(gamma.id)])

        assert [row.key for row in results.rows] == [str(gamma.id)]
        assert [grouping.key for grouping in results.groupings] == ["role", "usecase"]

    def test_flag_is_off_returns_no_data_even_with_a_cached_run(self) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        flush_persons_and_events()
        url = f"/api/projects/{self.team.id}/query/"
        first = self.client.post(url, {"query": self._query(), "refresh": "blocking"}, format="json")
        assert first.status_code == status.HTTP_200_OK
        assert [row["key"] for row in first.json()["results"]["rows"]] == [str(self.alpha.id), str(self.beta.id)]

        self.flag_enabled = False
        denied = self.client.post(url, {"query": self._query(), "refresh": "force_cache"}, format="json")

        assert denied.status_code == status.HTTP_400_BAD_REQUEST
        assert "results" not in denied.json()
        assert str(self.alpha.id) not in denied.content.decode()

    def test_flag_is_off_denies_the_runner_for_a_first_use_scan(self) -> None:
        self.flag_enabled = False
        query = BookActivityMatrixQuery(**self._query(includeFirstUse=True))
        runner = BookActivityMatrixQueryRunner(team=self.team, query=query, user=self.user)

        with self.assertRaises(UserAccessControlError), patch.object(runner, "_calculate") as calculate:
            runner.run(user=self.user)

        calculate.assert_not_called()

    def test_flag_is_evaluated_for_the_caller_with_organization_and_project_context(self) -> None:
        query = BookActivityMatrixQuery(**self._query())
        runner = BookActivityMatrixQueryRunner(team=self.team, query=query, user=self.user)

        assert runner.validate_query_runner_access(self.user) is True

        self.feature_enabled.assert_called_once()
        args, kwargs = self.feature_enabled.call_args
        assert args == (CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG, self.user.distinct_id)
        assert kwargs["groups"] == {"organization": str(self.team.organization_id), "project": str(self.team.id)}

    def test_force_enabled_flag_allows_the_runner_without_the_sdk(self) -> None:
        self.flag_enabled = False
        query = BookActivityMatrixQuery(**self._query())
        runner = BookActivityMatrixQueryRunner(team=self.team, query=query, user=self.user)

        with patch("posthog.permissions._FORCE_ENABLED_FLAGS", frozenset({CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG})):
            assert runner.validate_query_runner_access(self.user) is True

        self.feature_enabled.assert_not_called()

    def test_hides_an_account_the_caller_cannot_see_even_after_a_cached_run(self) -> None:
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)
        flush_persons_and_events()
        url = f"/api/projects/{self.team.id}/query/"
        payload = {"query": self._query(), "refresh": "blocking"}
        first = self.client.post(url, payload, format="json").json()
        assert [row["key"] for row in first["results"]["rows"]] == [str(self.alpha.id), str(self.beta.id)]

        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.alpha.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )
        second = self.client.post(url, payload, format="json").json()

        assert [row["key"] for row in second["results"]["rows"]] == [str(self.beta.id)]

    @parameterized.expand([("month", "-3m", "2026-10-01"), ("day", "-6m", None)])
    def test_buckets_months_and_caps_daily_ranges(self, interval: str, date_from: str, last_key: str | None) -> None:
        if last_key is None:
            with pytest.raises(ValidationError):
                self._run(interval=interval, dateRange=DateRange(date_from=date_from))
            return

        results = self._run(interval=interval, dateRange=DateRange(date_from=date_from))

        assert all(column.key.endswith("-01") for column in results.columns)
        assert (results.columns[-1].key, results.columns[-1].partial) == (last_key, True)
        assert [column.partial for column in results.columns[:-1]] == [False] * (len(results.columns) - 1)

    def test_returns_all_time_first_use_only_when_asked(self) -> None:
        self._event(ANA, "insight created", "2025-03-10T10:00:00Z", self.alpha)
        self._event(ANA, "insight created", "2026-10-26T10:00:00Z", self.alpha)

        assert self._run().firstUse is None
        first_use = self._run(includeFirstUse=True).firstUse

        assert first_use is not None
        assert {(item.row, item.series, item.date) for item in first_use} == {(str(self.alpha.id), "pa", "2025-03-10")}

    @parameterized.expand([("owner", False, status.HTTP_200_OK), ("another member", True, status.HTTP_403_FORBIDDEN)])
    def test_async_results_go_only_to_the_user_who_ran_them(self, _name: str, as_other: bool, expected: int) -> None:
        labels = get_query_runner(self._query(), self.team, user=self.user).query_status_labels()
        stored = QueryStatus(
            id="book-activity-matrix-query",
            team_id=self.team.id,
            complete=True,
            labels=labels,
            results={"results": {"rows": [{"key": str(self.alpha.id), "label": "Alpha"}]}},
        )
        if as_other:
            self.client.force_login(self.other_user)

        with patch("posthog.api.query.get_query_status", return_value=stored):
            response = self.client.get(f"/api/projects/{self.team.id}/query/book-activity-matrix-query/")

        assert response.status_code == expected, response.content
