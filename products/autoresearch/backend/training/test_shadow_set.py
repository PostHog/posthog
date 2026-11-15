from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone as django_timezone

from parameterized import parameterized

from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.autoresearch.backend.training.shadow_set import FITTED_METRIC_KEY, shadow_set

# (name, age in days, recipe_hash, bundle-backed, fitted)
Challenger = tuple[str, int, str, bool, bool]


class TestShadowSet(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        # horizon 7 + 7 matured dates: a challenger younger than 14 days keeps its place.
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Test", target_event="$pageview", horizon_days=7
        )
        self.now = django_timezone.now()

    def _model(
        self,
        name: str,
        *,
        role: str,
        age_days: int,
        recipe_hash: str,
        bundle: bool = True,
        fitted: bool = False,
        promoted: bool = False,
        metrics: dict | None = None,
        archived_days_ago: int = 0,
    ) -> AutoresearchModel:
        created_at = self.now - timedelta(days=age_days)
        model = AutoresearchModel.objects.create(
            pipeline=self.pipeline,
            role=role,
            recipe_hash=recipe_hash,
            model_recipe={},
            artifact_prefix=f"bundles/{name}" if bundle else "",
            metrics={**({FITTED_METRIC_KEY: True} if fitted else {}), **(metrics or {})},
            agent_description=name,
            promoted_at=created_at if promoted else None,
            archived_at=self.now - timedelta(days=archived_days_ago)
            if role == AutoresearchModel.Role.ARCHIVED
            else None,
        )
        AutoresearchModel.objects.filter(pk=model.pk).update(created_at=created_at)
        return model

    @parameterized.expand(
        [
            (
                "limit_of_three_keeps_the_newest",
                [
                    ("c20", 20, "a", True, True),
                    ("c21", 21, "b", True, True),
                    ("c22", 22, "c", True, True),
                    ("c23", 23, "d", True, True),
                ],
                False,
                ["champion", "c20", "c21", "c22"],
            ),
            (
                "duplicate_recipes_and_the_champion_recipe_are_skipped",
                [("c20", 20, "a", True, True), ("c21", 21, "a", True, True), ("c22", 22, "champ", True, True)],
                False,
                ["champion", "c20"],
            ),
            (
                "previous_champion_is_included",
                [("c20", 20, "a", True, True)],
                True,
                ["champion", "previous", "c20"],
            ),
            (
                "minimum_shadow_age_keeps_earlier_entrants",
                [
                    ("c0", 0, "a", True, True),
                    ("c1", 1, "b", True, True),
                    ("c2", 2, "c", True, True),
                    ("c3", 3, "d", True, True),
                ],
                False,
                ["champion", "c1", "c2", "c3"],
            ),
            (
                "a_newer_challenger_displaces_a_matured_one",
                [
                    ("c1", 1, "a", True, True),
                    ("c20", 20, "b", True, True),
                    ("c21", 21, "c", True, True),
                    ("c22", 22, "d", True, True),
                ],
                False,
                ["champion", "c1", "c20", "c21"],
            ),
            (
                "recipe_only_and_unfitted_challengers_are_excluded",
                [("recipe_only", 1, "a", False, True), ("unfitted", 2, "b", True, False), ("c3", 3, "c", True, True)],
                False,
                ["champion", "c3"],
            ),
        ]
    )
    def test_shadow_set_rules(self, _name, challengers: list[Challenger], with_previous: bool, expected: list[str]):
        self._model("champion", role=AutoresearchModel.Role.CHAMPION, age_days=1, recipe_hash="champ", promoted=True)
        if with_previous:
            self._model(
                "previous", role=AutoresearchModel.Role.ARCHIVED, age_days=30, recipe_hash="prev", promoted=True
            )
            # Archived without promotion: a challenger retired before it ever served.
            self._model("never_served", role=AutoresearchModel.Role.ARCHIVED, age_days=10, recipe_hash="x")
        for name, age_days, recipe_hash, bundle, fitted in challengers:
            self._model(
                name,
                role=AutoresearchModel.Role.CHALLENGER,
                age_days=age_days,
                recipe_hash=recipe_hash,
                bundle=bundle,
                fitted=fitted,
            )

        assert [m.agent_description for m in shadow_set(self.pipeline, now=self.now)] == expected

    def _shadow_runs(self, model: AutoresearchModel, failure_kinds: list[str]) -> None:
        for days_ago, failure_kind in enumerate(reversed(failure_kinds), start=1):
            run = AutoresearchRun.objects.create(
                pipeline=self.pipeline,
                model=model,
                run_type=AutoresearchRun.RunType.INFERENCE,
                status=AutoresearchRun.Status.FAILED,
                metrics={
                    "shadow": True,
                    "prediction_date": (self.now - timedelta(days=days_ago)).date().isoformat(),
                    "failure_kind": failure_kind,
                },
            )
            AutoresearchRun.objects.filter(pk=run.pk).update(created_at=self.now - timedelta(days=days_ago))

    @parameterized.expand(
        [
            (
                "archived_as_unscorable_is_skipped",
                {"archived_reason": "unscorable"},
                [],
                [],
                ["champion", "older", "c1"],
            ),
            (
                "two_repeatable_failures_skip_it",
                {},
                ["limit_exceeded", "query_failed"],
                [],
                ["champion", "older", "c1"],
            ),
            ("one_repeatable_failure_keeps_it", {}, ["limit_exceeded"], [], ["champion", "previous", "c1"]),
            ("transient_failures_keep_it", {}, ["other", "other"], [], ["champion", "previous", "c1"]),
            (
                "a_challenger_with_two_repeatable_failures_leaves",
                {},
                [],
                ["model_load_failed", "model_load_failed"],
                ["champion", "previous"],
            ),
        ]
    )
    def test_models_that_cannot_score_leave_the_set(
        self,
        _name,
        previous_metrics: dict,
        previous_failures: list[str],
        challenger_failures: list[str],
        expected: list[str],
    ):
        self._model("champion", role=AutoresearchModel.Role.CHAMPION, age_days=1, recipe_hash="champ", promoted=True)
        previous = self._model(
            "previous",
            role=AutoresearchModel.Role.ARCHIVED,
            age_days=30,
            recipe_hash="prev",
            promoted=True,
            metrics=previous_metrics,
        )
        self._model(
            "older",
            role=AutoresearchModel.Role.ARCHIVED,
            age_days=60,
            recipe_hash="older",
            promoted=True,
            archived_days_ago=30,
        )
        challenger = self._model("c1", role=AutoresearchModel.Role.CHALLENGER, age_days=1, recipe_hash="c", fitted=True)
        self._shadow_runs(previous, previous_failures)
        self._shadow_runs(challenger, challenger_failures)

        # One run-history query covers every candidate, however many failed.
        with self.assertNumQueries(6):
            members = shadow_set(self.pipeline, now=self.now)
        assert [m.agent_description for m in members] == expected
        assert AutoresearchModel.objects.filter(pipeline=self.pipeline).count() == 4
