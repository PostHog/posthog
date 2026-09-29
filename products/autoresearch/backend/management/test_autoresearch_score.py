from datetime import date, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend.inference.sandbox import SandboxInferenceError
from products.autoresearch.backend.management.commands import autoresearch_score
from products.autoresearch.backend.management.commands.autoresearch_score import Command
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.autoresearch.backend.testing import TeamScopedTestMixin


@time_machine.travel("2026-09-11T12:00:00Z", tick=False)
class TestResolvePredictionDates(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero_backfill_days_ran_live", {"backfill_days": 0}),
            ("negative_backfill_days_scored_nothing", {"backfill_days": -3}),
            ("future_date_read_as_live", {"prediction_date": "2026-09-12"}),
            ("unparseable_date", {"prediction_date": "yesterday"}),
        ]
    )
    def test_rejects_windows_that_would_score_the_wrong_days(self, _name, options):
        with self.assertRaises(CommandError):
            Command._resolve_prediction_dates(options)

    def test_backfill_window_ends_yesterday_oldest_first(self):
        dates = Command._resolve_prediction_dates({"backfill_days": 3})
        today = date.today()
        assert dates == [today - timedelta(days=3), today - timedelta(days=2), today - timedelta(days=1)]


class TestSeedFixtureBundle(TeamScopedTestMixin, BaseTest):
    def _pipeline_with_champion(self):
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="seed", target_event="$pageview", horizon_days=7
        )
        champion = AutoresearchModel.objects.create(
            pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION, model_recipe={"stub": True}, recipe_hash="old"
        )
        return pipeline, champion

    @parameterized.expand(
        [
            ("upload_fails", "write_bundle", OSError("storage down")),
            ("fit_fails", "fit_champion_model", SandboxInferenceError("train.py failed")),
        ]
    )
    def test_a_failed_step_leaves_the_current_champion_in_place(self, _name, step, error):
        pipeline, champion = self._pipeline_with_champion()
        with (
            patch.object(autoresearch_score, "write_bundle"),
            patch.object(autoresearch_score, "fit_champion_model"),
            patch.object(autoresearch_score, step, side_effect=error),
        ):
            with self.assertRaises(type(error)):
                call_command("autoresearch_score", "--pipeline-id", str(pipeline.pk), "--seed-fixture-bundle")
        champion.refresh_from_db()
        assert champion.role == AutoresearchModel.Role.CHAMPION
        assert (
            not AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
            .exclude(pk=champion.pk)
            .exists()
        )

    def test_the_fitted_fixture_becomes_champion_with_its_metrics(self):
        pipeline, old_champion = self._pipeline_with_champion()
        metrics = {"holdout_auc": 0.81, "n_train": 40, "n_features": 6}
        with (
            patch.object(autoresearch_score, "write_bundle"),
            patch.object(autoresearch_score, "fit_champion_model", return_value=metrics) as fit,
            patch.object(autoresearch_score, "run_inference_for_pipeline") as run,
        ):
            run.return_value.status = "completed"
            run.return_value.metrics = {}
            call_command("autoresearch_score", "--pipeline-id", str(pipeline.pk), "--seed-fixture-bundle")
        new_champion = AutoresearchModel.objects.get(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert new_champion.pk != old_champion.pk
        assert new_champion.holdout_score == 0.81
        assert fit.call_args.kwargs["prefix"] == new_champion.artifact_prefix
