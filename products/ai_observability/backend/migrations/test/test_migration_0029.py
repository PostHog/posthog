import importlib

from posthog.test.base import BaseTest

from django.apps import apps

from products.ai_observability.backend.models.evaluation_reports import EvaluationReport
from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationStatus, EvaluationStatusReason

disable_reports_for_disabled_evaluations = importlib.import_module(
    "products.ai_observability.backend.migrations.0029_disable_reports_for_disabled_evaluations"
).disable_reports_for_disabled_evaluations


class TestDisableReportsForDisabledEvaluationsMigration(BaseTest):
    def _create_evaluation(
        self,
        status: EvaluationStatus,
        status_reason: EvaluationStatusReason | None = None,
    ) -> Evaluation:
        return Evaluation.objects.create(
            team=self.team,
            name=f"{status} evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test"},
            output_type="boolean",
            output_config={},
            enabled=status == EvaluationStatus.ACTIVE,
            status=status,
            status_reason=status_reason,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )

    def test_only_paused_evaluations_disable_their_reports(self) -> None:
        paused_report = EvaluationReport.objects.create(
            team=self.team,
            evaluation=self._create_evaluation(EvaluationStatus.PAUSED),
        )
        errored_report = EvaluationReport.objects.create(
            team=self.team,
            evaluation=self._create_evaluation(
                EvaluationStatus.ERROR,
                EvaluationStatusReason.PROVIDER_KEY_RATE_LIMITED,
            ),
        )

        disable_reports_for_disabled_evaluations(apps, None)

        paused_report.refresh_from_db()
        errored_report.refresh_from_db()
        self.assertFalse(paused_report.enabled)
        self.assertTrue(errored_report.enabled)
