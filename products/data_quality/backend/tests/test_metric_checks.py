from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.data_catalog.backend.facade.api import upsert_metric
from products.data_catalog.backend.facade.models import Metric
from products.data_quality.backend.logic import checks
from products.data_quality.backend.logic.errors import CheckConfigError, SubjectUnresolvableError
from products.data_quality.backend.models import DataQualityCheck

HOGQL = {"kind": "HogQLQuery", "query": "SELECT 1 AS value"}
QUERY = "SELECT * FROM {metric} WHERE value < 1"


class TestMetricCheckAuthoring(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.id))
        self.enterContext(
            patch(
                "posthog.hogql.query.execute_hogql_query", side_effect=AssertionError("Authoring executed ClickHouse")
            )
        )

    def _metric(self, definition: dict | None = None) -> Metric:
        return upsert_metric(
            team=self.team, user=self.user, name="revenue", description="Revenue", definition=definition or HOGQL
        )

    def _create(
        self,
        metric: Metric,
        *,
        check_type: str = "custom_sql",
        column_name: str = "",
        config: dict | None = None,
        name: str = "",
        team: Team | None = None,
    ) -> tuple[DataQualityCheck, bool]:
        return checks.upsert_check(
            team=team or self.team,
            user=self.user,
            subject_type="metric",
            subject_uuid=str(metric.id),
            check_type=check_type,
            column_name=column_name,
            config=config or {"query": QUERY},
            name=name,
        )

    def test_authoring_reupserts_the_same_check(self) -> None:
        metric = self._metric()
        check, created = self._create(metric)
        assert created
        assert str(check.subject_uuid) == str(metric.id)
        repeated, created = self._create(metric, name="revenue_min")
        assert not created
        assert repeated.id == check.id

    @parameterized.expand(
        [
            ("wrong_type", HOGQL, {"check_type": "row_count", "config": {"min": 1}}),
            ("markdown", {"kind": "MarkdownDefinition", "markdown": "Count customers."}, {}),
            ("trends", {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}, {}),
            ("column", HOGQL, {"column_name": "value"}),
            ("missing_placeholder", HOGQL, {"config": {"query": "SELECT 1"}}),
            (
                "repeated_placeholder",
                HOGQL,
                {"config": {"query": "SELECT * FROM {metric} a JOIN {metric} b ON a.value = b.value"}},
            ),
            ("extra_placeholder", HOGQL, {"config": {"query": "SELECT * FROM {metric} WHERE value > {threshold}"}}),
            ("invalid_check", HOGQL, {"config": {"query": "SELECT FROM {metric}"}}),
            ("invalid_saved_query", {"kind": "HogQLQuery", "query": "SELECT ("}, {}),
        ]
    )
    def test_invalid_metric_check_is_rejected_before_saving(self, _name: str, definition: dict, options: dict) -> None:
        metric = self._metric(HOGQL if _name == "invalid_saved_query" else definition)
        if _name == "invalid_saved_query":
            metric.definition = definition
            metric.save(update_fields=["definition"])
        with self.assertRaises(CheckConfigError):
            self._create(metric, **options)
        assert not DataQualityCheck.objects.for_team(self.team.id).exists()

    @parameterized.expand([("deleted",), ("missing",), ("definitionless",)])
    def test_unavailable_metric_is_rejected(self, state: str) -> None:
        metric = self._metric()
        if state == "deleted":
            metric.deleted = True
            metric.save(update_fields=["deleted"])
        elif state == "missing":
            metric.id = uuid4()
        else:
            metric.definition = None
            metric.save(update_fields=["definition"])
        with self.assertRaises((CheckConfigError, SubjectUnresolvableError)):
            self._create(metric)

    def test_edit_validates_composition_and_preserves_definition_on_rejection(self) -> None:
        metric = self._metric()
        check, _ = self._create(metric)
        edited_query = "SELECT * FROM {metric} WHERE value < 2"
        checks.edit_check(team=self.team, check=check, editor=self.user, config={"query": edited_query})
        with self.assertRaises(CheckConfigError):
            checks.edit_check(team=self.team, check=check, editor=self.user, config={"query": "SELECT 1"})
        check.refresh_from_db()
        assert check.config == {"query": edited_query}
        assert check.definition_author == self.user

    def test_manual_suite_passes_metric_selector(self) -> None:
        metric = self._metric()
        with patch("products.data_quality.backend.logic.checks.sync_connect") as connect:
            connect.return_value.start_workflow = AsyncMock()
            suite = checks.start_check_suite(
                team=self.team, user=self.user, subject_type="metric", subject_uuids=[str(metric.id)]
            )
        assert suite.subject_uuid == str(metric.id)
        assert connect.return_value.start_workflow.call_args.args[1]["metric_ids"] == [str(metric.id)]
