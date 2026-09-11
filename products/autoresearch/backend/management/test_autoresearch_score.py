from datetime import date, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend.management.commands import autoresearch_score
from products.autoresearch.backend.management.commands.autoresearch_score import Command
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.autoresearch.backend.testing import TeamScopedTestMixin


class TestResolvePredictionDates(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero_backfill_days_ran_live", {"backfill_days": 0}),
            ("negative_backfill_days_scored_nothing", {"backfill_days": -3}),
            ("future_date_read_as_live", {"prediction_date": (date.today() + timedelta(days=1)).isoformat()}),
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
    def test_upload_failure_leaves_the_current_champion_in_place(self):
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="seed", target_event="$pageview", horizon_days=7
        )
        champion = AutoresearchModel.objects.create(
            pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION, model_recipe={"stub": True}, recipe_hash="old"
        )
        with patch.object(autoresearch_score, "write_bundle", side_effect=OSError("storage down")):
            with self.assertRaises(OSError):
                call_command("autoresearch_score", "--pipeline-id", str(pipeline.pk), "--seed-fixture-bundle")
        champion.refresh_from_db()
        assert champion.role == AutoresearchModel.Role.CHAMPION
        assert (
            not AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
            .exclude(pk=champion.pk)
            .exists()
        )
