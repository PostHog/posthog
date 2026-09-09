from contextlib import nullcontext
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.data_catalog.backend.facade.api import upsert_metric
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.logic.checks import upsert_check
from products.data_quality.backend.logic.runner import run_check
from products.data_quality.backend.logic.subject_access import (
    DenialContext,
    definition_reads_unreadable_subject,
    hidden_check_ids,
    pin_referenced_subjects,
    readable_subjects,
    referenced_subject_names,
    without_denied_runs,
)
from products.data_quality.backend.logic.subjects import resolve_subject
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestMetricSubjectAccess(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.metric_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="revenue_rows",
            format="Parquet",
            url_pattern="s3://bucket/revenue",
            columns={"amount": {"clickhouse": "Int64", "hogql": "integer"}},
        )
        self.extra_view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="thresholds", query={"kind": "HogQLQuery", "query": "SELECT 1 AS minimum"}
        )
        self.metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="revenue",
            description="Revenue",
            definition={"kind": "HogQLQuery", "query": "SELECT amount FROM revenue_rows"},
        )
        self.subject = resolve_subject(self.team.id, "metric", self.metric.id)
        self.config = {"query": "SELECT * FROM {metric} WHERE amount < (SELECT minimum FROM thresholds)"}

    @parameterized.expand(
        [("metric_table", {"revenue_rows"}, True), ("extra_table", {"thresholds"}, True), ("allowed", set(), False)]
    )
    def test_composed_references_control_access(self, _name: str, denied: set[str], expected: bool) -> None:
        database = Database.create_for(team=self.team, user=self.user)
        context = DenialContext(readable=readable_subjects(self.team.id, denied), denied=denied, database=database)
        assert (
            definition_reads_unreadable_subject(self.team.id, "custom_sql", self.config, context, subject=self.subject)
            is expected
        )

    def test_pins_both_saved_metric_and_check_references(self) -> None:
        assert set(referenced_subject_names(self.team.id, "custom_sql", self.config, subject=self.subject)) == {
            "revenue_rows",
            "thresholds",
        }
        pinned = pin_referenced_subjects(self.team.id, "custom_sql", self.config, subject=self.subject)
        assert pinned is not None
        assert {(ref["subject_type"], ref["subject_uuid"]) for ref in pinned} == {
            ("table", str(self.metric_table.id)),
            ("view", str(self.extra_view.id)),
        }

    @parameterized.expand([("allowed", set(), True), ("denied", {"revenue_rows"}, False)])
    def test_readable_metric_identity_controls_history(self, _name: str, denied: set[str], expected: bool) -> None:
        check, suite = self._check_and_suite()
        run = DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            quality_check=check,
            suite_run=suite,
            subject_type="metric",
            subject_uuid=self.metric.id,
            subject_name=self.metric.name,
            check_type="custom_sql",
            check_fingerprint=check.fingerprint,
            referenced_subjects=[],
            status="passed",
        )
        readable = readable_subjects(self.team.id, denied)
        assert readable.contains("metric", self.metric.id) is expected
        context = DenialContext(
            readable=readable, denied=denied, database=Database.create_for(team=self.team, user=self.user)
        )
        assert (
            without_denied_runs(DataQualityCheckRun.objects.for_team(self.team.id), context).filter(id=run.id).exists()
            is expected
        )

    def test_repeated_metric_checks_resolve_in_a_bounded_number_of_queries(self) -> None:
        check, _ = self._check_and_suite()
        context = DenialContext(
            readable=readable_subjects(self.team.id, set()),
            denied=set(),
            database=Database.create_for(team=self.team, user=self.user),
        )
        with self.assertNumQueries(4):
            assert hidden_check_ids(self.team.id, [check] * 20, context) == set()
        context.denied.add("thresholds")
        with self.assertNumQueries(2):
            assert hidden_check_ids(self.team.id, [check] * 20, context) == {check.id}

    def test_failed_composition_cannot_record_empty_references(self) -> None:
        assert pin_referenced_subjects(self.team.id, "custom_sql", {"query": "SELECT 1"}, subject=self.subject) is None

    def _check_and_suite(self) -> tuple[DataQualityCheck, DataQualitySuiteRun]:
        check, _ = upsert_check(
            team=self.team,
            user=self.user,
            subject_type="metric",
            subject_uuid=str(self.metric.id),
            check_type="custom_sql",
            column_name="",
            config=self.config,
        )
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", created_by=self.user
        )
        return check, suite

    @parameterized.expand([("metric_table",), ("extra_view",)])
    def test_runtime_denies_each_composed_warehouse_reference(self, denied_subject: str) -> None:
        check, suite = self._check_and_suite()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        subject = self.metric_table if denied_subject == "metric_table" else self.extra_view
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table" if denied_subject == "metric_table" else "warehouse_view",
            resource_id=str(subject.id),
            organization_member=self.organization_membership,
            access_level="none",
        )
        cache.clear()

        def execute_with_resolution(
            *, query: ast.SelectQuery, team: Team, user: User, bypass_warehouse_access_control: bool, **kwargs: object
        ) -> SimpleNamespace:
            prepare_ast_for_printing(
                query,
                HogQLContext(
                    team_id=team.id,
                    user=user,
                    enable_select_queries=True,
                    bypass_warehouse_access_control=bypass_warehouse_access_control,
                ),
                "clickhouse",
            )
            return SimpleNamespace(results=[[0, 0]], columns=["failure_count", "observed_value"])

        with (
            patch(
                "posthog.hogql.database.database.feature_enabled_or_false",
                side_effect=lambda name, *args, **kwargs: name == "hogql-warehouse-access-control",
            ),
            patch(
                "products.data_quality.backend.logic.runner.execute_hogql_query", side_effect=execute_with_resolution
            ),
        ):
            outcome = run_check(check, suite, self.team)
        assert outcome.status == "errored"
        assert subject.name in outcome.error

    @parameterized.expand(
        [
            ("success", False, False),
            ("engine_error", True, False),
            ("discovery_failure", False, True),
        ]
    )
    def test_run_pins_the_definition_executed_during_a_metric_edit(
        self, _name: str, engine_fails: bool, discovery_fails: bool
    ) -> None:
        check, suite = self._check_and_suite()

        def execute_with_edit(**kwargs: object) -> SimpleNamespace:
            upsert_metric(
                team=self.team,
                user=self.user,
                name="revenue",
                description="Revenue",
                definition={"kind": "HogQLQuery", "query": "SELECT 1 AS amount"},
            )
            if engine_fails:
                raise RuntimeError("Query execution failed")
            return SimpleNamespace(results=[[0, 0]], columns=["failure_count", "observed_value"])

        discovery = (
            patch(
                "products.data_quality.backend.logic.runner.pin_referenced_subjects",
                side_effect=[None, [{"subject_type": "view", "subject_uuid": str(self.extra_view.id)}]],
            )
            if discovery_fails
            else nullcontext()
        )
        with (
            discovery,
            patch("products.data_quality.backend.logic.runner.execute_hogql_query", side_effect=execute_with_edit),
        ):
            outcome = run_check(check, suite, self.team)
        assert outcome.status == ("errored" if engine_fails else "passed")
        run = DataQualityCheckRun.objects.for_team(self.team.id).get(quality_check=check)
        if discovery_fails:
            assert run.referenced_subjects is None
            return
        assert run.referenced_subjects is not None
        assert {ref["subject_uuid"] for ref in run.referenced_subjects} == {
            str(self.metric_table.id),
            str(self.extra_view.id),
        }
        assert "revenue_rows" in run.compiled_query
