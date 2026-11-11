from datetime import date, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.schema import AccountActivityMatrixEmptyReason, AccountActivityMatrixQuery, CacheMissResponse, QueryStatus

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.models import OrganizationMembership
from posthog.models.group_usage_metric import GroupUsageMetric
from posthog.test.persons import create_person
from posthog.week_start_day import WeekStartDay

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.hogql_queries.account_activity_matrix_query_runner import (
    AccountActivityMatrixQueryRunner,
)
from products.customer_analytics.backend.models import Account
from products.customer_analytics.backend.test.factories import create_account

ANA = "11111111-1111-4111-8111-111111111111"
BO = "22222222-2222-4222-8222-222222222222"
CY = "33333333-3333-4333-8333-333333333333"
DEE = "44444444-4444-4444-8444-444444444444"


@time_machine.travel("2026-10-28T18:00:00Z", tick=False)
class TestAccountActivityMatrixQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save()
        self.account = create_account(team_id=self.team.id, external_id="acme")
        self.insights = self._metric("Insights", "insight viewed")
        self.replay = self._metric("Replay", "recording viewed")
        for uuid, email in ((ANA, "ana@example.com"), (BO, "bo@example.com"), (CY, "cy@example.com")):
            create_person(team=self.team, uuid=uuid, distinct_ids=[uuid], properties={"email": email})

    def _metric(self, name: str, event: str, **kwargs: Any) -> GroupUsageMetric:
        return GroupUsageMetric.objects.create(
            team=self.team,
            group_type_index=0,
            name=name,
            filters=kwargs.pop("filters", {"events": [{"id": event, "type": "events", "order": 0}]}),
            **kwargs,
        )

    def _event(self, person: str, event: str, timestamp: str, group_key: str = "acme") -> None:
        _create_event(
            team=self.team,
            event=event,
            distinct_id=person,
            person_id=person,
            timestamp=timestamp,
            properties={"$group_0": group_key},
        )

    def _deny_access(self, resource: str) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=str(self.account.id) if resource == "account" else None,
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

    def _run(self, account: Account | None = None, **kwargs: Any) -> Any:
        flush_persons_and_events()
        query = AccountActivityMatrixQuery(accountId=str((account or self.account).id), **kwargs)
        return AccountActivityMatrixQueryRunner(team=self.team, query=query, user=self.user).calculate().results

    def test_counts_each_person_week_and_metric_for_the_account_only(self) -> None:
        self._event(ANA, "insight viewed", "2026-10-26T10:00:00Z")
        self._event(ANA, "insight viewed", "2026-10-27T10:00:00Z")
        self._event(ANA, "recording viewed", "2026-10-20T10:00:00Z")
        self._event(BO, "insight viewed", "2026-10-26T10:00:00Z")
        self._event(BO, "insight viewed", "2026-10-26T11:00:00Z", group_key="globex")
        self._event(CY, "pageview", "2026-10-26T10:00:00Z")

        results = self._run()

        assert {(cell.row, cell.column, cell.series, cell.value) for cell in results.data} == {
            (ANA, "2026-10-25", str(self.insights.id), 2.0),
            (ANA, "2026-10-18", str(self.replay.id), 1.0),
            (BO, "2026-10-25", str(self.insights.id), 1.0),
        }
        assert [(row.key, row.label) for row in results.rows] == [(ANA, "ana@example.com"), (BO, "bo@example.com")]
        assert [series.label for series in results.series] == ["Insights", "Replay"]

    def test_keeps_the_most_active_persons_and_flags_truncation(self) -> None:
        for _ in range(3):
            self._event(BO, "insight viewed", "2026-10-26T10:00:00Z")
        self._event(ANA, "insight viewed", "2026-10-26T10:00:00Z")

        results = self._run(rowLimit=1)

        assert [row.key for row in results.rows] == [BO]
        assert {cell.row for cell in results.data} == {BO}
        assert results.truncated is True

    @parameterized.expand(
        [
            (WeekStartDay.SUNDAY, "2026-10-25T05:30:00Z", "2026-10-18", "2026-10-25"),
            (WeekStartDay.MONDAY, "2026-10-26T05:30:00Z", "2026-10-19", "2026-10-26"),
        ]
    )
    def test_buckets_weeks_in_the_project_timezone(
        self, week_start_day: WeekStartDay, timestamp: str, expected_week: str, current_week: str
    ) -> None:
        self.team.timezone = "America/Los_Angeles"
        self.team.week_start_day = week_start_day
        self.team.save()
        self._event(ANA, "insight viewed", timestamp)

        results = self._run()

        assert [cell.column for cell in results.data] == [expected_week]
        assert [column.key for column in results.columns][-2:] == [expected_week, current_week]
        assert [column.partial for column in results.columns] == [False] * 7 + [True]

    @parameterized.expand(
        [
            ("no_external_id", AccountActivityMatrixEmptyReason.NO_EXTERNAL_ID),
            ("no_group_type", AccountActivityMatrixEmptyReason.NO_GROUP_TYPE),
            ("no_metrics", AccountActivityMatrixEmptyReason.NO_METRICS),
        ]
    )
    def test_returns_an_empty_reason_instead_of_querying(
        self, case: str, expected_reason: AccountActivityMatrixEmptyReason
    ) -> None:
        account = self.account
        skipped: set[str] = set()
        if case == "no_external_id":
            account = create_account(team_id=self.team.id, name="No key")
        if case == "no_group_type":
            config = self.team.customer_analytics_config
            type(config).objects.filter(pk=config.pk).update(account_group_type_index=None)
            config.refresh_from_db()
        if case == "no_metrics":
            GroupUsageMetric.objects.filter(team=self.team).delete()
            warehouse_filters = {"source": GroupUsageMetric.Source.DATA_WAREHOUSE, "table_name": "charges"}
            skipped = {
                str(self._metric("Revenue", "", filters=warehouse_filters).id),
                str(self._metric("Everything", "", filters={}).id),
            }
        self._event(ANA, "insight viewed", "2026-10-26T10:00:00Z")

        results = self._run(account=account)

        assert results.emptyReason == expected_reason
        assert results.data == []
        assert set(results.skippedMetricIds) == skipped

    @parameterized.expand(
        [(resource, refresh) for resource in ("account", "person") for refresh in ("blocking", "force_cache")]
    )
    def test_denies_restricted_access_even_when_cached(self, resource: str, refresh: str) -> None:
        self._event(ANA, "insight viewed", "2026-10-26T10:00:00Z")
        flush_persons_and_events()
        payload = {
            "query": {"kind": "AccountActivityMatrixQuery", "accountId": str(self.account.id)},
            "refresh": "blocking",
        }
        url = f"/api/projects/{self.team.id}/query/"
        assert self.client.post(url, payload, format="json").status_code == status.HTTP_200_OK

        self._deny_access(resource)
        response = self.client.post(url, {**payload, "refresh": refresh}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Access control failure" in response.json()["detail"]
        with self.assertRaises(UserAccessControlError):
            AccountActivityMatrixQueryRunner(
                team=self.team, query=AccountActivityMatrixQuery(accountId=str(self.account.id))
            ).calculate()

    def test_cache_only_read_without_a_user_misses_cached_results(self) -> None:
        self._event(ANA, "insight viewed", "2026-10-26T10:00:00Z")
        flush_persons_and_events()
        query = {"kind": "AccountActivityMatrixQuery", "accountId": str(self.account.id)}
        get_query_runner(query, self.team, user=self.user).run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user)

        response = get_query_runner(query, self.team).run(ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)

        assert isinstance(response, CacheMissResponse)

    @parameterized.expand([("relinked", "acme"), ("newly_linked", None)])
    def test_cached_activity_follows_the_current_group_key(self, _name: str, external_id: str | None) -> None:
        Account.objects.for_team(self.team.id).filter(id=self.account.id).update(external_id=external_id)
        self._event(BO, "insight viewed", "2026-10-26T10:00:00Z", group_key="new-group")
        flush_persons_and_events()
        query = {"kind": "AccountActivityMatrixQuery", "accountId": str(self.account.id)}
        first = get_query_runner(query, self.team, user=self.user).run(
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user
        )
        assert first.results.rows == []

        Account.objects.for_team(self.team.id).filter(id=self.account.id).update(external_id="new-group")
        refreshed = get_query_runner(query, self.team, user=self.user).run(
            ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE, user=self.user
        )
        assert [row.key for row in refreshed.results.rows] == [BO]

    @parameterized.expand(
        [
            ("visible", None, status.HTTP_200_OK),
            ("hidden_account", "account", status.HTTP_403_FORBIDDEN),
            ("hidden_persons", "person", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_async_result_retrieval_repeats_the_access_check(
        self, _name: str, resource: str | None, expected: int
    ) -> None:
        if resource:
            self._deny_access(resource)
        stored = QueryStatus(
            id="account-activity-matrix-query",
            team_id=self.team.id,
            complete=True,
            labels=get_query_runner(
                {"kind": "AccountActivityMatrixQuery", "accountId": str(self.account.id)}, self.team, user=self.user
            ).query_status_labels(),
            results={"results": {"rows": [{"key": ANA, "label": "ana@example.com"}]}},
        )

        with patch("posthog.api.query.get_query_status", return_value=stored):
            response = self.client.get(f"/api/projects/{self.team.id}/query/account-activity-matrix-query/")

        assert response.status_code == expected, response.content

    def test_returns_every_person_week_past_the_default_row_limit(self) -> None:
        create_person(team=self.team, uuid=DEE, distinct_ids=[DEE], properties={"email": "dee@example.com"})
        first_week = date(2026, 5, 3)
        for person in (ANA, BO, CY, DEE):
            for week in range(26):
                self._event(person, "insight viewed", f"{first_week + timedelta(weeks=week, days=1)}T12:00:00Z")

        results = self._run(weeks=26)

        assert len(results.rows) == 4
        assert len(results.data) == 104
        assert results.truncated is False
