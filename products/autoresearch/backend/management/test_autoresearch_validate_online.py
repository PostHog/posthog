from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from products.autoresearch.backend.management.commands import autoresearch_validate_online
from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.testing import TeamScopedTestMixin


class TestValidateOnlineCommand(TeamScopedTestMixin, BaseTest):
    def test_a_failed_date_exits_non_zero(self):
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Test", target_event="$pageview", horizon_days=7
        )
        failed = AutoresearchRun(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.FAILED,
            error="clickhouse unavailable",
            metrics={"prediction_date": "2026-09-01"},
        )

        with (
            patch.object(autoresearch_validate_online, "run_online_validation_for_pipeline", return_value=[failed]),
            self.assertRaises(CommandError),
        ):
            call_command("autoresearch_validate_online", "--pipeline-id", str(pipeline.pk))
