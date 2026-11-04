from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import batched
from uuid import UUID, uuid4

import time_machine
from unittest.mock import patch

from django.db import DatabaseError, connection
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.tasks.ai_observability_usage_report import _get_all_ai_observability_reports
from posthog.tasks.usage_report import _get_all_org_reports, iter_reports_with_usage_counter_metadata
from posthog.temporal.usage_report.aggregator import iter_org_reports
from posthog.temporal.usage_report.types import WorkflowContext
from posthog.usage_counters import UsageCounterComparisonRows, UsageCounterMode, UsageCounterReport
from posthog.utils import DayRange

from products.ai_observability.backend.models.offline_evaluations import OfflineEvaluationUsageLedger
from products.ai_observability.backend.offline_evaluation_billing import get_offline_evaluation_usage

from ee.billing.quota_limiting import _aggregate_quota_usage, _iter_quota_organizations, update_all_orgs_billing_quotas


@time_machine.travel("2026-10-31T12:00:00Z", tick=False)
class TestOfflineEvaluationBilling(TestCase):
    organization: Organization
    other_organization: Organization
    team: Team
    other_team: Team

    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization, _, cls.team = Organization.objects.bootstrap(None)
        cls.other_organization, _, cls.other_team = Organization.objects.bootstrap(None)

    def setUp(self) -> None:
        self.period = DayRange(start=datetime(2026, 10, 31, tzinfo=UTC), end=datetime(2026, 11, 1, tzinfo=UTC))
        self.ctx = WorkflowContext(
            run_id="offline-usage-test",
            date_str="2026-10-31",
            period_start=self.period.start,
            period_end=self.period.end,
        )

    def record(self, team: Team, quantity: int, *, at: datetime | None = None) -> OfflineEvaluationUsageLedger:
        return OfflineEvaluationUsageLedger.objects.for_team(team.id).create(
            team_id=team.id,
            organization_id=team.organization_id,
            experiment_id=uuid4(),
            accepted_at=at or self.period.start,
            quantity=quantity,
        )

    @parameterized.expand([(-1, 0), (0, 7), (86_399_999_999, 7), (86_400_000_000, 0)])
    def test_utc_half_open_month_boundary(self, microseconds: int, expected: int) -> None:
        self.record(self.team, 7, at=self.period.start + timedelta(microseconds=microseconds))
        usage = get_offline_evaluation_usage(self.period.start, self.period.end)
        self.assertEqual(sum(usage.get(str(self.organization.id), {}).values()), expected)

    @parameterized.expand([(False,), (True,)])
    def test_sums_quantities_for_moved_teams_but_excludes_deleted_teams(self, deleted_team: bool) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        self.record(child, 20)
        self.record(child, 10)
        self.record(self.team, 5)
        self.record(self.other_team, 9)
        child.organization = self.other_organization
        child.save(update_fields=["organization"])
        self.record(child, 4)
        child_id = child.id
        if deleted_team:
            child.delete()
        expected = {
            str(self.organization.id): {self.team.id: 5},
            str(self.other_organization.id): {self.other_team.id: 9},
        }
        if not deleted_team:
            expected[str(self.organization.id)][child_id] = 30
            expected[str(self.other_organization.id)][child_id] = 4
        before = list(OfflineEvaluationUsageLedger.objects.unscoped().order_by("id").values())
        for _ in range(2):
            usage = get_offline_evaluation_usage(self.period.start, self.period.end)
            self.assertEqual(usage, expected)
            reports = {report.organization_id: report for report in iter_org_reports(defaultdict(dict), self.ctx, {})}
            self.assertEqual(reports[str(self.organization.id)].ai_event_count_in_period, 5 if deleted_team else 35)
            self.assertEqual(
                reports[str(self.other_organization.id)].ai_event_count_in_period, 9 if deleted_team else 13
            )
            if deleted_team:
                self.assertNotIn(str(child_id), reports[str(self.organization.id)].teams)
            else:
                self.assertEqual(reports[str(self.organization.id)].teams[str(child_id)].ai_event_count_in_period, 30)
        self.assertEqual(list(OfflineEvaluationUsageLedger.objects.unscoped().order_by("id").values()), before)

    @parameterized.expand([(False,), (True,)])
    def test_organization_without_live_teams_has_no_reported_usage(self, demo: bool) -> None:
        self.record(self.team, 30)
        Team.objects.filter(id=self.team.id).update(is_demo=demo)
        self.team.delete()
        usage = get_offline_evaluation_usage(self.period.start, self.period.end)
        self.assertEqual(usage, {})
        reports = {report.organization_id: report for report in iter_org_reports(defaultdict(dict), self.ctx, {})}
        self.assertNotIn(str(self.organization.id), reports)
        self.assertEqual(list(_iter_quota_organizations([], usage)), [])
        quotas = _aggregate_quota_usage([], defaultdict(dict), offline_usage=usage)
        self.assertEqual(quotas.usage, {})
        self.assertEqual(OfflineEvaluationUsageLedger.objects.unscoped().get().quantity, 30)

    @parameterized.expand([(1,), (2,)])
    def test_offline_quota_organizations_survive_closed_server_cursors(self, batch_size: int) -> None:
        historical_organizations = [self.organization, Organization.objects.create(), Organization.objects.create()]
        for organization in historical_organizations:
            self.team.organization = organization
            self.team.save(update_fields=["organization"])
            self.record(self.team, 10)
        self.team.organization = self.other_organization
        self.team.save(update_fields=["organization"])
        self.record(self.team, 7)
        usage = get_offline_evaluation_usage(self.period.start, self.period.end)

        organizations: list[tuple[UUID, list[int]]] = []
        with (
            patch.dict(connection.settings_dict, DISABLE_SERVER_SIDE_CURSORS=False),
            patch("ee.billing.quota_limiting.QUOTA_ORGANIZATION_BATCH_SIZE", batch_size),
        ):
            for batch in batched(
                _iter_quota_organizations([self.team, self.other_team], usage), batch_size, strict=False
            ):
                with connection.cursor() as cursor:
                    cursor.execute("CLOSE ALL")
                organizations.extend((organization.id, [team.id for team in teams]) for organization, teams in batch)

        self.assertEqual(
            organizations,
            [
                (self.other_organization.id, [self.team.id, self.other_team.id]),
                *[(organization.id, []) for organization in sorted(historical_organizations, key=lambda org: org.id)],
            ],
        )

    def test_grouped_query_cost_does_not_grow_with_upload_count(self) -> None:
        for _ in range(20):
            self.record(self.team, 3)
        with self.assertNumQueries(1):
            self.assertEqual(
                get_offline_evaluation_usage(self.period.start, self.period.end),
                {str(self.organization.id): {self.team.id: 60}},
            )

    def test_historical_team_does_not_duplicate_ingested_shadow_comparisons(self) -> None:
        self.record(self.team, 30)
        Team.objects.filter(id=self.team.id).update(organization=self.other_organization)
        field = "teams_with_ai_event_count_in_period"
        counter_report = UsageCounterReport(
            counts={field: [(self.team.id, 50)]},
            usage_sources={field: UsageCounterMode.BOTH},
            counter_comparisons={
                field: UsageCounterComparisonRows(
                    legacy_by_team={self.team.id: 50},
                    realtime_by_team={self.team.id: {str(self.other_organization.id): 55}},
                )
            },
        )
        reports = {
            report.organization_id: report
            for report in iter_reports_with_usage_counter_metadata(
                iter_org_reports(defaultdict(dict, {field: {self.team.id: 50}}), self.ctx, {}),
                counter_report,
                caller="usage_reports_v2",
                date="2026-10-31",
            )
        }
        old = reports[str(self.organization.id)]
        new = reports[str(self.other_organization.id)]
        self.assertEqual(old.ai_event_count_in_period, 30)
        self.assertEqual(new.ai_event_count_in_period, 50)
        self.assertEqual(old.counter_comparisons, {field: {"legacy": 0, "realtime": 0}})
        self.assertEqual(new.counter_comparisons, {field: {"legacy": 50, "realtime": 55}})

    def test_current_demo_and_internal_status_excludes_usage(self) -> None:
        demo_team = Team.objects.create(organization=self.organization, is_demo=True)
        self.record(demo_team, 30)
        self.record(self.team, 10)
        self.record(self.other_team, 9)
        self.other_organization.for_internal_metrics = True
        self.other_organization.save(update_fields=["for_internal_metrics"])
        self.assertEqual(
            get_offline_evaluation_usage(self.period.start, self.period.end),
            {str(self.organization.id): {self.team.id: 10}},
        )
        Team.objects.filter(id=self.team.id).update(is_demo=True)
        Team.objects.filter(id=demo_team.id).update(is_demo=False)
        self.assertEqual(
            get_offline_evaluation_usage(self.period.start, self.period.end),
            {str(self.organization.id): {demo_team.id: 30}},
        )

    def test_deleted_organization_is_not_recreated(self) -> None:
        self.record(self.team, 30)
        self.organization.delete()
        self.assertEqual(get_offline_evaluation_usage(self.period.start, self.period.end), {})
        self.assertEqual(OfflineEvaluationUsageLedger.objects.unscoped().get().quantity, 30)

    @parameterized.expand([("celery",), ("temporal",), ("analytics",), ("quota",)])
    def test_ledger_failure_prevents_incomplete_reports_and_quota_updates(self, path: str) -> None:
        self.organization.usage = {"llm_events": {"usage": 50, "todays_usage": 30, "limit": 100}}
        self.organization.save(update_fields=["usage"])

        def fail_ledger_read(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: object
        ) -> object:
            if sql.startswith("SELECT") and OfflineEvaluationUsageLedger._meta.db_table in sql:
                raise DatabaseError("Ledger unavailable")
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(fail_ledger_read),
            self.assertRaisesMessage(DatabaseError, "Ledger unavailable"),
        ):
            if path == "celery":
                _get_all_org_reports(period=self.period)
            elif path == "temporal":
                list(iter_org_reports(defaultdict(dict), self.ctx, {}))
            elif path == "analytics":
                _get_all_ai_observability_reports(period=self.period)
            else:
                update_all_orgs_billing_quotas()
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.usage["llm_events"], {"usage": 50, "todays_usage": 30, "limit": 100})
