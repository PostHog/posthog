from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from parameterized import parameterized

from products.ai_observability.backend.eval_suggestions.coverage import (
    MAX_SILENT_EVALUATIONS,
    ExistingEval,
    best_replacement,
    covers,
    existing_evals,
    fetch_coverage,
    find_fixes,
    fix_dedupe_key,
)
from products.ai_observability.backend.models.evaluations import Evaluation

ALL_TRAFFIC = [{"id": "all", "rollout_percentage": 100, "properties": []}]
SECURITY_LENS = {"key": "review_lens", "value": ["security-1", "security-2"], "operator": "exact", "type": "event"}
AUTH_LENS = {"key": "review_lens", "value": ["auth"], "operator": "exact", "type": "event"}


def _existing(**overrides: Any) -> ExistingEval:
    fields: dict[str, Any] = {
        "id": "existing",
        "name": "Existing check",
        "evaluation_type": "hog",
        "enabled": True,
        "target": "trace",
        "conditions": ALL_TRAFFIC,
        "template_key": None,
        "dedupe_key": None,
        "source_hash": None,
        "prompt": None,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
        **overrides,
    }
    return ExistingEval(**fields)


@parameterized.expand(
    [
        ("enabled_on_all_traffic", _existing(), [], True),
        ("sampled_rollout_still_counts", _existing(conditions=[{**ALL_TRAFFIC[0], "rollout_percentage": 5}]), [], True),
        ("disabled", _existing(enabled=False), [], False),
        ("another_unit", _existing(target="generation"), [], False),
        (
            "scoped_to_another_environment",
            _existing(conditions=[{**ALL_TRAFFIC[0], "properties": [{"key": "env", "value": ["staging"]}]}]),
            [],
            False,
        ),
        (
            "wider_filter",
            _existing(
                conditions=[{**ALL_TRAFFIC[0], "properties": [{**SECURITY_LENS, "value": ["security-1", "auth"]}]}]
            ),
            [AUTH_LENS],
            True,
        ),
        (
            "another_segment",
            _existing(conditions=[{**ALL_TRAFFIC[0], "properties": [SECURITY_LENS]}]),
            [AUTH_LENS],
            False,
        ),
        ("no_condition_sets_match_nothing", _existing(conditions=[]), [], False),
        ("zero_rollout_never_runs", _existing(conditions=[{**ALL_TRAFFIC[0], "rollout_percentage": 0}]), [], False),
        # The API saves a set without a rollout as running on all its traffic.
        ("missing_rollout_runs_everywhere", _existing(conditions=[{"id": "all", "properties": []}]), [], True),
    ]
)
def test_covers(_name: str, existing: ExistingEval, filters: list[dict[str, Any]], expected: bool) -> None:
    assert covers(existing, "trace", filters) is expected


@parameterized.expand(
    [
        ("renamed_with_a_suffix", "signals", {"signals_scout": 900, "billing": 50}, "signals_scout"),
        # Far apart by length, but the live value holds the stale one whole.
        ("renamed_with_a_long_suffix", "chat", {"chat_assistant": 900, "billing": 50}, "chat_assistant"),
        ("close_spelling", "checkout", {"chekout": 40, "search": 900}, "chekout"),
        ("nothing_similar", "signals", {"billing": 900, "search": 50}, None),
        # The busier base value would widen the eval to every checkout, so the closer version wins.
        ("versioned_value", "checkout_v2", {"checkout": 900, "checkout_v3": 40}, "checkout_v3"),
        ("short_values_never_match", "3", {"13": 900, "4": 50}, None),
    ]
)
def test_best_replacement(_name: str, old: str, values: dict[str, int], expected: str | None) -> None:
    assert best_replacement(old, values) == expected


class TestFetchCoverage(ClickhouseTestMixin, APIBaseTest):
    def _evaluation(
        self,
        name: str,
        product: str | None,
        *,
        age: timedelta = timedelta(days=40),
        evaluation_type: str = "llm_judge",
        rollout: int = 100,
    ) -> Evaluation:
        conditions = (
            [
                {
                    "id": "scoped",
                    "rollout_percentage": rollout,
                    "properties": [{"key": "ai_product", "value": [product], "operator": "exact", "type": "event"}],
                }
            ]
            if product is not None
            else []
        )
        evaluation = Evaluation.objects.create(
            team=self.team,
            name=name,
            evaluation_type=evaluation_type,
            evaluation_config={"prompt": "Return true when the finding cites its data."}
            if evaluation_type == "llm_judge"
            else {"source": "return true"},
            output_type="boolean",
            output_config={},
            target="trace",
            enabled=True,
            conditions=conditions,
        )
        # A brand-new evaluation has had no chance to run, so age it past the grace periods.
        Evaluation.objects.filter(pk=evaluation.pk).update(
            created_at=timezone.now() - age, updated_at=timezone.now() - min(age, timedelta(days=10))
        )
        return evaluation

    def test_an_evaluation_whose_filter_value_went_stale_gets_a_patch(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        stale = self._evaluation("Scout findings are grounded", "signals")
        running = self._evaluation("Billing answers are grounded", "billing")
        for hours in range(1, 4):
            for product in ("signals_scout", "billing"):
                _create_event(
                    team=self.team,
                    event="$ai_generation",
                    distinct_id="user-1",
                    timestamp=end - timedelta(hours=hours),
                    properties={"$ai_trace_id": f"{product}-{hours}", "ai_product": product},
                )
        _create_event(
            team=self.team,
            event="$ai_evaluation",
            distinct_id="user-1",
            timestamp=end - timedelta(hours=1),
            properties={"$ai_evaluation_id": str(running.id), "$ai_evaluation_result": True},
        )

        coverage = fetch_coverage(self.team, end - timedelta(days=7), end)

        assert [fix.evaluation_id for fix in coverage.fixes] == [str(stale.id)]
        fix = coverage.fixes[0]
        assert fix.filter_change is not None
        assert (fix.filter_change.old_value, fix.filter_change.new_value) == ("signals", "signals_scout")
        assert fix.patch is not None
        assert fix.patch["conditions"][0]["properties"][0]["value"] == ["signals_scout"]

    def _generations(self, end: datetime, products: tuple[str, ...]) -> None:
        for hours in range(1, 4):
            for product in products:
                _create_event(
                    team=self.team,
                    event="$ai_generation",
                    distinct_id="user-1",
                    timestamp=end - timedelta(hours=hours),
                    properties={"$ai_trace_id": f"{product}-{hours}", "ai_product": product},
                )

    def test_dead_evaluations_without_a_patch(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generations(end, ("billing",))
        no_match = self._evaluation("Nothing like it", "voice")
        no_conditions = self._evaluation("No condition sets", None)
        self._evaluation("Too new to judge", "voice", age=timedelta(days=3))

        coverage = fetch_coverage(self.team, end - timedelta(days=7), end)

        assert sorted((fix.evaluation_id, fix.patch, fix.has_conditions) for fix in coverage.fixes) == sorted(
            [(str(no_match.id), None, True), (str(no_conditions.id), None, False)]
        )

    @parameterized.expand(
        [
            ("skipped", {"$ai_evaluation_skipped": "true"}),
            ("not_applicable", {"$ai_evaluation_applicable": False}),
        ]
    )
    def test_runs_that_graded_nothing_leave_an_evaluation_silent(self, _name: str, run: dict[str, Any]) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generations(end, ("billing",))
        silent = self._evaluation("Voice answers are grounded", "voice")
        _create_event(
            team=self.team,
            event="$ai_evaluation",
            distinct_id="user-1",
            timestamp=end - timedelta(hours=1),
            properties={"$ai_evaluation_id": str(silent.id), **run},
        )

        coverage = fetch_coverage(self.team, end - timedelta(days=7), end)

        assert [fix.evaluation_id for fix in coverage.fixes] == [str(silent.id)]

    def test_a_set_paused_at_zero_rollout_does_not_count_as_matching_traffic(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generations(end, ("signals_scout", "billing"))
        evaluation = self._evaluation("Scout findings are grounded", "signals")
        paused = {
            "id": "paused",
            "rollout_percentage": 0,
            "properties": [{"key": "ai_product", "value": ["billing"], "operator": "exact", "type": "event"}],
        }
        Evaluation.objects.filter(pk=evaluation.pk).update(conditions=[*evaluation.conditions, paused])

        coverage = fetch_coverage(self.team, end - timedelta(days=7), end)

        [fix] = coverage.fixes
        assert fix.filter_change is not None
        assert fix.filter_change.new_value == "signals_scout"

    @parameterized.expand(
        [
            ("same_reasoning_for_both_answers", True, 40, True),
            ("distinct_reasoning", False, 40, False),
            # The runs mostly judged the version before the edit, so they say nothing about the current one.
            ("edited_within_the_window", True, 10, False),
        ]
    )
    def test_one_outcome_needs_shared_reasoning(
        self, _name: str, shared: bool, edited_days_ago: int, expected_fix: bool
    ) -> None:
        end = timezone.now() - timedelta(minutes=30)
        evaluation = self._evaluation("Always passes", None, evaluation_type="hog")
        Evaluation.objects.filter(pk=evaluation.pk).update(
            conditions=ALL_TRAFFIC, updated_at=timezone.now() - timedelta(days=edited_days_ago)
        )
        for index in range(210):
            result = index >= 5
            reasoning = "The answer cites its data correctly." if shared else f"Run {index}: the answer is {result}."
            _create_event(
                team=self.team,
                event="$ai_evaluation",
                distinct_id="user-1",
                timestamp=end - timedelta(hours=1),
                properties={
                    "$ai_evaluation_id": str(evaluation.id),
                    "$ai_evaluation_result": result,
                    "$ai_evaluation_reasoning": reasoning,
                },
            )

        coverage = fetch_coverage(self.team, end - timedelta(days=7), end)

        assert [fix.problem for fix in coverage.fixes] == (["one_outcome"] if expected_fix else [])

    def test_a_built_in_sentiment_eval_counts_as_the_sentiment_template(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        Evaluation.objects.create(
            team=self.team,
            name="User frustration",
            evaluation_type="sentiment",
            evaluation_config={},
            output_type="sentiment",
            output_config={},
            target="generation",
            enabled=True,
            conditions=ALL_TRAFFIC,
        )

        coverage = fetch_coverage(self.team, end - timedelta(days=7), end)

        assert [e.template_key for e in coverage.evals] == ["sentiment"]

    def test_a_repair_that_matches_nothing_does_not_stop_the_search(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._generations(end, ("signals_scout", "billing"))
        product = {"key": "ai_product", "operator": "exact", "type": "event"}
        evaluation = self._evaluation("Two branches", None)
        # The first branch still matches nothing once `signals` becomes `signals_scout`, since no traffic is staging.
        Evaluation.objects.filter(pk=evaluation.pk).update(
            conditions=[
                {
                    "id": "a",
                    "rollout_percentage": 100,
                    "properties": [
                        {**product, "value": ["signals"]},
                        {"key": "env", "value": ["staging"], "operator": "exact", "type": "event"},
                    ],
                },
                {"id": "b", "rollout_percentage": 100, "properties": [{**product, "value": ["billng"]}]},
            ]
        )

        coverage = fetch_coverage(self.team, end - timedelta(days=7), end)

        [fix] = coverage.fixes
        assert fix.filter_change is not None
        assert (fix.filter_change.old_value, fix.filter_change.new_value) == ("billng", "billing")
        assert fix.patch is not None
        assert fix.patch["conditions"][0]["properties"][0]["value"] == ["signals"]

    def test_only_the_most_recently_edited_silent_evaluations_are_probed(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        for index in range(MAX_SILENT_EVALUATIONS + 2):
            self._evaluation(f"Silent {index}", f"gone-{index}")

        coverage = fetch_coverage(self.team, end - timedelta(days=7), end)

        assert len(coverage.fixes) == MAX_SILENT_EVALUATIONS

    def test_dismissed_fixes_leave_room_for_the_next_silent_evaluation(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        evaluations = [
            self._evaluation(f"Silent {index}", f"gone-{index}") for index in range(MAX_SILENT_EVALUATIONS + 1)
        ]
        for index, evaluation in enumerate(evaluations):
            Evaluation.objects.filter(pk=evaluation.pk).update(updated_at=timezone.now() - timedelta(days=10 + index))
        dismissed = frozenset(fix_dedupe_key(str(e.id), "no_runs") for e in evaluations[:MAX_SILENT_EVALUATIONS])

        fixes = find_fixes(self.team, existing_evals(self.team), end - timedelta(days=7), end, dismissed)

        assert [fix.evaluation_id for fix in fixes] == [str(evaluations[-1].id)]

    def test_an_evaluation_paused_at_zero_rollout_gets_no_filter_repair(self) -> None:
        end = timezone.now() - timedelta(minutes=30)
        self._evaluation("Scout findings are grounded", "signals", rollout=0)
        self._generations(end, ("signals_scout",))

        assert fetch_coverage(self.team, end - timedelta(days=7), end).fixes == []
