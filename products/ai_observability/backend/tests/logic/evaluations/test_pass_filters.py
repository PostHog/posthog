from collections.abc import Callable

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.ai_observability.backend.facade.api import get_evaluation_pass_filters
from products.ai_observability.backend.facade.evaluation_signals import evaluation_output_changed
from products.ai_observability.backend.models.evaluations import Evaluation

CATEGORY_OPTIONS = [{"key": "ok", "label": "Ok"}, {"key": "bad", "label": "Bad"}]


def _evaluation(team, output_type: str = "boolean", output_config: dict | None = None, **fields) -> Evaluation:
    fields = {"evaluation_type": "hog", "evaluation_config": {"source": "return true"}, **fields}
    return Evaluation.objects.create(
        team=team, name="e", output_type=output_type, output_config=output_config or {}, **fields
    )


class TestEvaluationPassFilters(ClickhouseTestMixin, BaseTest):
    def test_grades_each_kind_of_run_by_its_evaluation_rule(self) -> None:
        plain = _evaluation(self.team)
        detector = _evaluation(self.team, output_config={"true_is_failure": True})
        deleted_detector = _evaluation(self.team, output_config={"true_is_failure": True}, deleted=True)
        numeric = _evaluation(self.team, "numeric", {"passing_rule": {"operator": "gte", "threshold": 4}})
        numeric_without_rule = _evaluation(self.team, "numeric", {})
        categorical = _evaluation(
            self.team,
            "categorical",
            {"options": CATEGORY_OPTIONS, "selection_mode": "single", "passing_rule": {"categories": ["ok"]}},
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

        filters = get_evaluation_pass_filters(self.team.id)
        response = execute_hogql_query(
            f"""
            SELECT
                JSONExtractString(properties, 'case'),
                countIf({filters.graded}) > 0,
                countIf({filters.passed}) > 0,
                countIf({filters.graded} AND NOT {filters.passed}) > 0
            FROM events
            WHERE event = '$ai_evaluation'
            GROUP BY 1
            """,
            team=self.team,
        )

        graded_passed_failed = {
            case: (bool(graded), bool(passed), bool(failed)) for case, graded, passed, failed in response.results
        }
        assert graded_passed_failed == {
            case: (graded, passed, graded and not passed) for case, (_, _, (graded, passed)) in cases.items()
        }


def _save(evaluation: Evaluation, **changes: object) -> None:
    for field, value in changes.items():
        setattr(evaluation, field, value)
    evaluation.save()


def _save_name_only(evaluation: Evaluation) -> None:
    evaluation.output_config = {"true_is_failure": True}
    evaluation.name = "renamed"
    evaluation.save(update_fields=["name"])


class TestEvaluationOutputChangedSignal(BaseTest):
    @parameterized.expand(
        [
            ("created", None, True),
            ("output config changed", lambda e: _save(e, output_config={"true_is_failure": True}), True),
            ("full save without an output change", lambda e: _save(e, name="renamed"), True),
            ("status update", lambda e: e.set_status("paused", None), False),
            ("output edited but only the name saved", _save_name_only, False),
        ]
    )
    def test_notifies_on_saves_that_write_the_output(
        self, _name: str, change: Callable[[Evaluation], None] | None, should_notify: bool
    ) -> None:
        evaluation = None if change is None else _evaluation(self.team)
        notified: list[int] = []
        evaluation_output_changed.connect(
            lambda **kwargs: notified.append(kwargs["team_id"]), weak=False, dispatch_uid="test-output-changed"
        )
        self.addCleanup(evaluation_output_changed.disconnect, dispatch_uid="test-output-changed")

        with self.captureOnCommitCallbacks(execute=True):
            if change is None:
                _evaluation(self.team)
            else:
                assert evaluation is not None
                change(evaluation)

        assert notified == ([self.team.id] if should_notify else [])
