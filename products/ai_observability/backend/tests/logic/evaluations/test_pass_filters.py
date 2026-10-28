from collections.abc import Callable

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

from products.ai_observability.backend.logic.evaluations.pass_filters import (
    PassRules,
    build_evaluation_pass_filters,
    build_pass_rules,
)
from products.ai_observability.backend.models.evaluations import Evaluation

CATEGORY_OPTIONS = [{"key": "ok", "label": "Ok"}, {"key": "bad", "label": "Bad"}]


def _evaluation(team, output_type: str = "boolean", output_config: dict | None = None, **fields) -> Evaluation:
    fields = {"evaluation_type": "hog", "evaluation_config": {"source": "return true"}, **fields}
    return Evaluation.objects.create(
        team=team, name="e", output_type=output_type, output_config=output_config or {}, **fields
    )


def _per_evaluation_rules(team_id: int, _evaluation_ids: list[str]) -> PassRules:
    filters = build_evaluation_pass_filters(team_id)
    return PassRules(graded=parse_expr(filters.graded), passes=parse_expr(filters.passed))


class TestEvaluationPassFilters(ClickhouseTestMixin, BaseTest):
    @parameterized.expand([("per_evaluation", _per_evaluation_rules), ("by_kind_of_rule", build_pass_rules)])
    def test_grades_each_kind_of_run_by_its_evaluation_rule(
        self, _name: str, build: Callable[[int, list[str]], PassRules]
    ) -> None:
        plain = _evaluation(self.team)
        detector = _evaluation(self.team, output_config={"true_is_failure": True})
        deleted_detector = _evaluation(self.team, output_config={"true_is_failure": True}, deleted=True)
        numeric = _evaluation(self.team, "numeric", {"passing_rule": {"operator": "gte", "threshold": 4}})
        numeric_lower = _evaluation(self.team, "numeric", {"passing_rule": {"operator": "gte", "threshold": 2}})
        numeric_at_most = _evaluation(self.team, "numeric", {"passing_rule": {"operator": "lte", "threshold": 4}})
        numeric_without_rule = _evaluation(self.team, "numeric", {})
        categorical = _evaluation(
            self.team,
            "categorical",
            {"options": CATEGORY_OPTIONS, "selection_mode": "single", "passing_rule": {"categories": ["ok"]}},
        )
        bad_passes = _evaluation(
            self.team,
            "categorical",
            {"options": CATEGORY_OPTIONS, "selection_mode": "multiple", "passing_rule": {"categories": ["bad"]}},
        )
        empty_passes = _evaluation(
            self.team,
            "categorical",
            {"options": CATEGORY_OPTIONS, "selection_mode": "multiple", "passing_rule": {"categories": []}},
        )
        sentiment = _evaluation(self.team, "sentiment", {}, evaluation_type="sentiment", evaluation_config={})

        cases: dict[str, tuple[Evaluation, dict, tuple[bool, bool]]] = {
            "plain true": (plain, {"$ai_evaluation_result": True}, (True, True)),
            "plain false": (plain, {"$ai_evaluation_result": False}, (True, False)),
            "plain skipped": (plain, {"$ai_evaluation_result": False, "$ai_evaluation_skipped": True}, (False, False)),
            "plain n/a": (plain, {"$ai_evaluation_applicable": False}, (False, False)),
            "detector true": (detector, {"$ai_evaluation_result": True}, (True, False)),
            "detector false": (detector, {"$ai_evaluation_result": False}, (True, True)),
            "deleted detector false": (deleted_detector, {"$ai_evaluation_result": False}, (True, True)),
            "numeric at threshold": (numeric, {"$ai_evaluation_numeric_result": 4}, (True, True)),
            "numeric below threshold": (numeric, {"$ai_evaluation_numeric_result": 3.5}, (True, False)),
            "lower threshold below the other": (numeric_lower, {"$ai_evaluation_numeric_result": 3.5}, (True, True)),
            "at most, above": (numeric_at_most, {"$ai_evaluation_numeric_result": 4.5}, (True, False)),
            "at most, at threshold": (numeric_at_most, {"$ai_evaluation_numeric_result": 4}, (True, True)),
            "numeric n/a": (
                numeric,
                {"$ai_evaluation_numeric_result": 5, "$ai_evaluation_applicable": False},
                (False, False),
            ),
            "numeric skipped": (
                numeric,
                {"$ai_evaluation_numeric_result": 5, "$ai_evaluation_skipped": True},
                (False, False),
            ),
            "numeric without rule": (numeric_without_rule, {"$ai_evaluation_numeric_result": 5}, (False, False)),
            "categorical passing key": (
                categorical,
                {"$ai_evaluation_categorical_result": ["ok"], "$ai_evaluation_applicable": True},
                (True, True),
            ),
            "categorical failing key": (
                categorical,
                {"$ai_evaluation_categorical_result": ["bad"], "$ai_evaluation_applicable": True},
                (True, False),
            ),
            "other passing key": (
                bad_passes,
                {"$ai_evaluation_categorical_result": ["bad"], "$ai_evaluation_applicable": True},
                (True, True),
            ),
            "other passing key, both chosen": (
                bad_passes,
                {"$ai_evaluation_categorical_result": ["ok", "bad"], "$ai_evaluation_applicable": True},
                (True, False),
            ),
            "empty passes, empty": (
                empty_passes,
                {"$ai_evaluation_categorical_result": [], "$ai_evaluation_applicable": True},
                (True, True),
            ),
            "empty passes, key": (
                empty_passes,
                {"$ai_evaluation_categorical_result": ["bad"], "$ai_evaluation_applicable": True},
                (True, False),
            ),
            "sentiment": (sentiment, {"$ai_sentiment_label": "positive"}, (False, False)),
            "boolean run before the switch to sentiment": (
                sentiment,
                {"$ai_evaluation_result_type": "boolean", "$ai_evaluation_result": True},
                (False, False),
            ),
        }
        for case, (evaluation, properties, _) in cases.items():
            _create_event(
                team=self.team,
                event="$ai_evaluation",
                distinct_id="user",
                properties={
                    "case": case,
                    "$ai_evaluation_id": str(evaluation.id),
                    "$ai_evaluation_result_type": evaluation.output_type,
                    **properties,
                },
            )
        flush_persons_and_events()

        rules = build(self.team.id, list({str(evaluation.id) for evaluation, _, _ in cases.values()}))
        response = execute_hogql_query(
            """
            SELECT
                JSONExtractString(properties, 'case'),
                countIf({graded}) > 0,
                countIf({graded} AND {passes}) > 0,
                countIf({graded} AND NOT {passes}) > 0
            FROM events
            WHERE event = '$ai_evaluation'
            GROUP BY 1
            """,
            team=self.team,
            placeholders={"graded": rules.graded, "passes": rules.passes},
        )

        graded_passed_failed = {
            case: (bool(graded), bool(passed), bool(failed)) for case, graded, passed, failed in response.results
        }
        assert graded_passed_failed == {
            case: (graded, passed, graded and not passed) for case, (_, _, (graded, passed)) in cases.items()
        }
