from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from parameterized import parameterized

from products.ai_observability.backend.eval_suggestions.coverage import (
    ExistingEval,
    best_replacement,
    covers,
    fetch_coverage,
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
    ]
)
def test_covers(_name: str, existing: ExistingEval, filters: list[dict[str, Any]], expected: bool) -> None:
    assert covers(existing, "trace", filters) is expected


@parameterized.expand(
    [
        ("renamed_with_a_suffix", "signals", {"signals_scout": 900, "billing": 50}, "signals_scout"),
        ("close_spelling", "checkout", {"chekout": 40, "search": 900}, "chekout"),
        ("nothing_similar", "signals", {"billing": 900, "search": 50}, None),
    ]
)
def test_best_replacement(_name: str, old: str, values: dict[str, int], expected: str | None) -> None:
    assert best_replacement(old, values) == expected


class TestFetchCoverage(ClickhouseTestMixin, APIBaseTest):
    def _evaluation(
        self, name: str, product: str | None, *, age: timedelta = timedelta(days=40), evaluation_type: str = "llm_judge"
    ) -> Evaluation:
        conditions = (
            [
                {
                    "id": "scoped",
                    "rollout_percentage": 100,
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

        assert sorted((fix.evaluation_id, fix.patch) for fix in coverage.fixes) == sorted(
            [(str(no_match.id), None), (str(no_conditions.id), None)]
        )

    @parameterized.expand([("same_reasoning_for_both_answers", True), ("distinct_reasoning", False)])
    def test_one_outcome_needs_shared_reasoning(self, _name: str, shared: bool) -> None:
        end = timezone.now() - timedelta(minutes=30)
        evaluation = self._evaluation("Always passes", None, evaluation_type="hog")
        Evaluation.objects.filter(pk=evaluation.pk).update(conditions=ALL_TRAFFIC)
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

        assert [fix.problem for fix in coverage.fixes] == (["one_outcome"] if shared else [])

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
