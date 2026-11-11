from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.utils import timezone

from parameterized import parameterized

from products.ai_observability.backend.eval_suggestions.coverage import (
    MAX_SILENT_EVALUATIONS,
    ExistingEval,
    best_replacement,
    covers,
    fetch_coverage,
    fix_dedupe_key,
    no_runs_fixes,
    one_outcome_fixes,
    silent_evaluations,
    suspicious_runs,
)
from products.ai_observability.backend.logic.eval_suggestions.coverage_queries import (
    EvaluationRunCounts,
    SharedReasoningRow,
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


NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _aged(**overrides: Any) -> ExistingEval:
    return _existing(**{"created_at": NOW - timedelta(days=40), "updated_at": NOW - timedelta(days=10), **overrides})


def test_only_the_most_recently_edited_silent_evaluations_are_probed() -> None:
    evals = [
        _aged(id=f"silent-{index}", updated_at=NOW - timedelta(days=10 + index))
        for index in range(MAX_SILENT_EVALUATIONS + 2)
    ]

    silent = silent_evaluations({e.id: e for e in evals}, [], frozenset(), NOW)

    assert [e.id for e in silent] == [e.id for e in evals[:MAX_SILENT_EVALUATIONS]]


def test_dismissed_fixes_leave_room_for_the_next_silent_evaluation() -> None:
    evals = [
        _aged(id=f"silent-{index}", updated_at=NOW - timedelta(days=10 + index))
        for index in range(MAX_SILENT_EVALUATIONS + 1)
    ]
    dismissed = frozenset(fix_dedupe_key(e.id, "no_runs") for e in evals[:MAX_SILENT_EVALUATIONS])

    silent = silent_evaluations({e.id: e for e in evals}, [], dismissed, NOW)

    assert [e.id for e in silent] == [evals[-1].id]


@parameterized.expand(
    [
        ("running_on_traffic", _aged(), True),
        ("paused_at_zero_rollout", _aged(conditions=[{**ALL_TRAFFIC[0], "rollout_percentage": 0}]), False),
    ]
)
def test_an_evaluation_paused_at_zero_rollout_gets_no_filter_repair(
    _name: str, existing: ExistingEval, expected: bool
) -> None:
    assert bool(silent_evaluations({existing.id: existing}, [], frozenset(), NOW)) is expected


def _matching_generations(generations: list[dict[str, str]]) -> Callable[[list[dict[str, Any]]], int]:
    def count(conditions: list[dict[str, Any]]) -> int:
        return sum(
            any(
                all(generation.get(prop["key"]) in prop["value"] for prop in condition["properties"])
                for condition in conditions
            )
            for generation in generations
        )

    return count


def test_a_repair_that_matches_nothing_does_not_stop_the_search() -> None:
    product = {"key": "ai_product", "operator": "exact", "type": "event"}
    # The first branch still matches nothing once `signals` becomes `signals_scout`, since no traffic is staging.
    existing = _aged(
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
    live = {"ai_product": {"signals_scout": 3, "billing": 3}}

    [fix] = no_runs_fixes(
        [existing],
        7,
        _matching_generations([{"ai_product": "signals_scout"}, {"ai_product": "billing"}]),
        lambda key: live.get(key, {}),
    )

    assert fix.filter_change is not None
    assert (fix.filter_change.old_value, fix.filter_change.new_value) == ("billng", "billing")
    assert fix.patch is not None
    assert fix.patch["conditions"][0]["properties"][0]["value"] == ["signals"]


@parameterized.expand(
    [
        ("same_reasoning_for_both_answers", 210, 40, True),
        ("distinct_reasoning", 0, 40, False),
        # The runs mostly judged the version before the edit, so they say nothing about the current one.
        ("edited_within_the_window", 210, 10, False),
    ]
)
def test_one_outcome_needs_shared_reasoning(
    _name: str, shared_runs: int, edited_days_ago: int, expected_fix: bool
) -> None:
    existing = _aged(updated_at=NOW - timedelta(days=edited_days_ago))
    enabled = {existing.id: existing}
    runs = [EvaluationRunCounts(evaluation_id=existing.id, runs=210, true_runs=205, false_runs=5)]
    shared = [SharedReasoningRow(evaluation_id=existing.id, shared_runs=shared_runs)]

    fixes = one_outcome_fixes(suspicious_runs(enabled, runs, NOW), shared, enabled, 7)

    assert [fix.problem for fix in fixes] == (["one_outcome"] if expected_fix else [])
