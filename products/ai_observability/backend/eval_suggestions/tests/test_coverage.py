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
    def _evaluation(self, name: str, product: str) -> Evaluation:
        evaluation = Evaluation.objects.create(
            team=self.team,
            name=name,
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Return true when the finding cites its data."},
            output_type="boolean",
            output_config={},
            target="trace",
            enabled=True,
            conditions=[
                {
                    "id": "scoped",
                    "rollout_percentage": 100,
                    "properties": [{"key": "ai_product", "value": [product], "operator": "exact", "type": "event"}],
                }
            ],
        )
        # A brand-new evaluation has had no chance to run, so age it past the grace periods.
        Evaluation.objects.filter(pk=evaluation.pk).update(
            created_at=timezone.now() - timedelta(days=40), updated_at=timezone.now() - timedelta(days=10)
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
