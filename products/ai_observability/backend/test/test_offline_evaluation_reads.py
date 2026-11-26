from dataclasses import replace
from datetime import datetime, timedelta
from sys import float_info
from uuid import uuid4

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.ai_observability.backend.api.offline_experiment_read_serializers import (
    OfflineScorerHistoryQuerySerializer,
)
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
    PayloadState,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition, ScoreDefinitionVersion
from products.ai_observability.backend.offline_evaluation_read_service import OfflineEvaluationReadService
from products.ai_observability.backend.offline_evaluation_read_types import (
    OfflineHistoryBreakdown,
    OfflineReadQuery,
    OfflineStatusCounts,
)
from products.ai_observability.backend.offline_evaluation_service import (
    OfflineEvaluationNotFound,
    OfflineEvaluationValidationError,
)
from products.ai_observability.backend.offline_evaluation_types import JSONValue, ResultValue
from products.ai_observability.backend.offline_payload_retention import OfflinePayloadRetention
from products.ai_observability.backend.read_pagination import decode_cursor, encode_cursor


class TestOfflineReadQuery(SimpleTestCase):
    @parameterized.expand([("!",), ("a" * 2049,), (encode_cursor(["id", "extra"]),), ("bnVsbA",)])
    def test_rejects_malformed_or_wrong_shape_cursor(self, cursor: str) -> None:
        with self.assertRaises(ValueError):
            decode_cursor(cursor, 1)

    def test_rejects_unbounded_pages_and_scorer_cells(self) -> None:
        for limit in (0, 101):
            with self.assertRaises(OfflineEvaluationValidationError):
                OfflineReadQuery(limit=limit)
        with self.assertRaises(OfflineEvaluationValidationError):
            OfflineReadQuery(scorer_version_ids=tuple(uuid4() for _ in range(21)))


class TestOfflineEvaluationReads(TestCase):
    team: Team
    other_team: Team
    numeric: ScoreDefinitionVersion
    numeric_v2: ScoreDefinitionVersion
    boolean: ScoreDefinitionVersion
    categorical: ScoreDefinitionVersion

    @classmethod
    def setUpTestData(cls) -> None:
        organization, _, cls.team = Organization.objects.bootstrap(None)
        cls.other_team = Team.objects.create(organization=organization)
        numeric = ScoreDefinition.objects.create(team=cls.team, name="Quality", kind="numeric")
        cls.numeric = numeric.create_new_version(config={}, created_by=None)
        cls.numeric_v2 = numeric.create_new_version(config={}, created_by=None)
        boolean = ScoreDefinition.objects.create(team=cls.team, name="Contains defect", kind="boolean")
        cls.boolean = boolean.create_new_version(config={}, created_by=None)
        categorical = ScoreDefinition.objects.create(team=cls.team, name="Topic", kind="categorical")
        cls.categorical = categorical.create_new_version(
            config={
                "selection_mode": "multiple",
                "options": [
                    {"key": "a", "label": "Alpha"},
                    {"key": "b", "label": "Beta"},
                    {"key": "c", "label": "Gamma"},
                ],
            },
            created_by=None,
        )

    def setUp(self) -> None:
        self.service = OfflineEvaluationReadService(
            team_id=self.team.id, user_access_control=None, can_read_scores=True
        )
        self.now = timezone.now()

    def test_experiment_score_resolves_observed_versions_and_pools_by_successful_item(self) -> None:
        experiment = self._experiment()
        definition = ScoreDefinition.objects.create(
            team=self.team, name="Overall", scope="experiment", kind="numeric", calculation="composite"
        )
        spec = {"alias": "quality", "scorer_version_id": str(self.numeric.id), "statistic": "mean"}

        def pin(policy: str) -> None:
            experiment.experiment_scorer_version = definition.create_new_version(
                config={},
                composition={"expression": "quality", "inputs": [{**spec, "version_policy": policy}]},
                created_by=None,
            )
            experiment.save(update_fields=["experiment_scorer_version"])

        first = self._item(experiment)
        self._result(first, self.numeric_v2, 0.75)
        pin("run")
        score = self.service.get_experiment(experiment.id).experiment_score
        assert score is not None
        self.assertEqual(score.value, 0.75)
        self.assertEqual(score.inputs[0].sources[0].version_id, self.numeric_v2.id)
        for other_status in ("error", "skipped", "not_applicable"):
            item = self._item(experiment)
            self._result(item, self.numeric, 0.0)
            self._result(item, self.numeric_v2, status=other_status)
        score = self.service.get_experiment(experiment.id).experiment_score
        assert score is not None
        self.assertEqual((score.status, score.value), ("mixed_versions", None))
        self.assertEqual([source.successful_items for source in score.inputs[0].sources], [3, 1])
        pin("combine")
        score = self.service.get_experiment(experiment.id).experiment_score
        assert score is not None
        self.assertEqual((score.status, score.value), ("ok", 0.75 / 4))
        self._result(first, self.numeric, 1.0)
        score = self.service.get_experiment(experiment.id).experiment_score
        assert score is not None
        self.assertEqual((score.status, score.value), ("overlapping_items", None))
        pin("exact")
        score = self.service.get_experiment(experiment.id).experiment_score
        assert score is not None
        self.assertEqual(score.value, 0.25)
        experiment.status = OfflineExperiment.Status.FAILED
        experiment.save(update_fields=["status"])
        failed = self.service.get_experiment(experiment.id).experiment_score
        assert failed is not None
        self.assertEqual((failed.status, failed.value), ("failed", None))

    def test_only_successful_versions_contribute_and_pending_and_formula_errors_have_no_verdict(self) -> None:
        run = self._experiment(status="uploading")
        definition = ScoreDefinition.objects.create(
            team=self.team, name="Ratio", scope="experiment", kind="numeric", calculation="composite"
        )
        run.experiment_scorer_version = definition.create_new_version(
            config={},
            composition={
                "expression": "1 / quality",
                "inputs": [{"alias": "quality", "scorer_version_id": str(self.numeric.id), "statistic": "mean"}],
            },
            created_by=None,
        )
        run.save(update_fields=["experiment_scorer_version"])

        def check(expected: str):
            score = self.service.get_experiment(run.id).experiment_score
            assert score is not None
            self.assertEqual((score.status, score.value, score.passed), (expected, None, None))
            return score

        check("pending")
        run.status = "completed"
        run.finished_at = self.now
        run.save(update_fields=["status", "finished_at"])
        self._result(self._item(run), self.numeric, status="error")
        self._result(self._item(run), self.numeric_v2, status="skipped")
        empty = check("no_successful_items")
        self.assertEqual([s.successful_items for s in empty.inputs[0].sources], [0, 0])
        self._result(self._item(run), self.numeric, 0.0)
        invalid = check("formula_error")
        self.assertEqual(invalid.inputs[0].status, "ok")
        self.assertEqual([s.successful_items for s in invalid.inputs[0].sources], [1, 0])

    def test_pooled_pass_rate_uses_exact_counts_at_the_threshold(self) -> None:
        run = self._experiment()
        newer = self.boolean.definition.create_new_version(config={}, created_by=None)
        for version, values in [(self.boolean, [True, False]), (newer, [True, False, False])]:
            for value in values:
                self._result(self._item(run), version, value)
        scorer = ScoreDefinition.objects.create(
            team=self.team, scope="experiment", name="Gate", calculation="composite", kind="numeric"
        )
        run.experiment_scorer_version = scorer.create_new_version(
            config={"passing_rule": {"operator": "gte", "threshold": 0.4}},
            composition={
                "expression": "rate",
                "inputs": [
                    {
                        "alias": "rate",
                        "statistic": "pass_rate",
                        "version_policy": "combine",
                        "scorer_version_id": str(self.boolean.id),
                    }
                ],
            },
            created_by=None,
        )
        run.save(update_fields=["experiment_scorer_version"])
        score = self.service.get_experiment(run.id).experiment_score
        assert score is not None
        self.assertEqual((score.status, score.value, score.passed), ("ok", 0.4, True))

    def test_pooled_mean_stays_finite_at_the_numeric_limit(self) -> None:
        experiment = self._experiment()
        formula = ScoreDefinition.objects.create(
            team=self.team, scope="experiment", name="Pooled quality", calculation="composite", kind="numeric"
        )
        experiment.experiment_scorer_version = formula.create_new_version(
            config={},
            composition={
                "expression": "quality",
                "inputs": [
                    {
                        "alias": "quality",
                        "statistic": "mean",
                        "version_policy": "combine",
                        "scorer_version_id": str(self.numeric.id),
                    }
                ],
            },
            created_by=None,
        )
        experiment.save(update_fields=["experiment_scorer_version"])
        third = self.numeric.definition.create_new_version(config={}, created_by=None)
        for version, count in [(self.numeric, 12), (self.numeric_v2, 2), (third, 12)]:
            for _ in range(count):
                self._result(self._item(experiment), version, float_info.max)
        score = self.service.get_experiment(experiment.id).experiment_score
        assert score is not None
        self.assertEqual((score.status, score.value), ("ok", float_info.max))

    def test_formula_uses_category_rate_and_boolean_polarity_and_keeps_missing_inputs_unset(self) -> None:
        experiment = self._experiment()
        boolean = self.boolean.definition.create_new_version(config={"true_is_failure": True}, created_by=None)
        source = str(boolean.id)
        inputs = [
            {"alias": "passed", "statistic": "pass_rate", "scorer_version_id": source},
            {"alias": "flagged", "statistic": "true_rate", "scorer_version_id": source},
            {
                "alias": "alpha",
                "statistic": "category_rate",
                "category": "a",
                "scorer_version_id": str(self.categorical.id),
            },
        ]

        def preview():
            return self.service.preview_experiment_score(
                experiment.id,
                composition={"expression": "0.5 * passed + 0.3 * flagged + 0.2 * alpha", "inputs": inputs},
                kind="numeric",
                config={},
            )

        first = self._item(experiment)
        second = self._item(experiment)
        self._result(first, boolean, True)
        self._result(second, boolean, True)
        missing = preview()
        self.assertEqual((missing.status, missing.value), ("missing_input", None))
        self._result(first, self.categorical, ["a"])
        self._result(second, self.categorical, ["b"])
        score = preview()
        self.assertEqual({row.alias: row.value for row in score.inputs}, {"passed": 0, "flagged": 1, "alpha": 0.5})
        self.assertEqual(score.value, 0.4)

    def _experiment(
        self,
        *,
        name: str = "Experiment",
        started_at: datetime | None = None,
        status: str = "completed",
        run_source: str | None = None,
    ) -> OfflineExperiment:
        return OfflineExperiment.objects.for_team(self.team.id).create(
            id=uuid4(),
            team=self.team,
            name=name,
            started_at=started_at or self.now,
            created_at=self.now,
            finished_at=None if status == "uploading" else self.now,
            status=status,
            run_source=run_source,
            submission_fingerprint="a" * 64,
        )

    def _item(
        self,
        experiment: OfflineExperiment,
        *,
        case_key: str | None = None,
        trial: str | None = None,
        model_version: str | None = None,
    ) -> OfflineExperimentItem:
        return OfflineExperimentItem.objects.for_team(self.team.id).create(
            id=uuid4(),
            team=self.team,
            experiment=experiment,
            case_key=case_key,
            model_version=model_version,
            trial=trial,
            submission_fingerprint="a" * 64,
        )

    def _result(
        self,
        item: OfflineExperimentItem,
        version: ScoreDefinitionVersion,
        value: ResultValue | None = None,
        *,
        status: str = "ok",
    ) -> OfflineEvaluationResult:
        return OfflineEvaluationResult.objects.for_team(self.team.id).create(
            team=self.team,
            item=item,
            scorer_definition_id=version.definition_id,
            scorer_version=version,
            status=status,
            numeric_value=value if isinstance(value, float) else None,
            boolean_value=value if isinstance(value, bool) else None,
            categorical_values=value if isinstance(value, list) else None,
            submission_fingerprint="a" * 64,
        )

    def _payload(self, owner: OfflineExperimentItem | OfflineEvaluationResult, data: dict[str, JSONValue]) -> None:
        owner.payload_state = PayloadState.AVAILABLE
        owner.payload_expires_at = owner.accepted_at + timedelta(days=30)
        owner.save(update_fields=["payload_state", "payload_expires_at"])
        if isinstance(owner, OfflineExperimentItem):
            OfflineExperimentItemPayload.objects.for_team(self.team.id).create(team=self.team, item=owner, data=data)
        else:
            OfflineEvaluationResultPayload.objects.for_team(self.team.id).create(
                team=self.team, result=owner, data=data
            )

    def test_complete_typed_aggregates_preserve_versions_statuses_and_coverage(self) -> None:
        experiment = self._experiment()
        items = [
            self._item(experiment, case_key=case_key, trial=trial)
            for case_key, trial in [
                ("first", "1"),
                ("first", "2"),
                ("second", "1"),
                (None, "1"),
                (None, "1"),
                (None, None),
            ]
        ]
        self._result(items[0], self.numeric, 0.0)
        self._result(items[1], self.numeric, 2.0)
        for item, status in zip(items[2:5], ("error", "skipped", "not_applicable")):
            self._result(item, self.numeric, status=status)
        self._result(items[0], self.numeric_v2, status="error")
        self._result(items[0], self.boolean, False)
        self._result(items[1], self.boolean, True)
        self._result(items[0], self.categorical, ["a", "b"])
        self._result(items[1], self.categorical, ["a"])

        summaries = {
            summary.scorer.id: summary
            for summary in self.service.list_summaries(experiment.id, OfflineReadQuery()).results
        }
        numeric = summaries[self.numeric.id]
        self.assertEqual(numeric.mean, 1.0)
        self.assertEqual(numeric.status_counts, OfflineStatusCounts(ok=2, error=1, skipped=1, not_applicable=1))
        self.assertEqual((numeric.observed_item_count, numeric.result_count, numeric.missing_result_count), (6, 5, 1))
        self.assertEqual(
            (numeric.distinct_case_count, numeric.items_with_case_key_count, numeric.items_without_case_key_count),
            (2, 3, 3),
        )
        self.assertEqual((numeric.trial_item_count, numeric.distinct_trial_count), (5, 5))
        self.assertIsNone(summaries[self.numeric_v2.id].mean)
        boolean = summaries[self.boolean.id]
        self.assertEqual((boolean.true_count, boolean.false_count, boolean.true_rate), (1, 1, 0.5))
        self.assertEqual((boolean.pass_count, boolean.fail_count, boolean.pass_rate), (1, 1, 0.5))
        for summary in summaries.values():
            if summary.scorer.kind != "boolean":
                self.assertEqual((summary.pass_count, summary.fail_count, summary.pass_rate), (None, None, None))
        self.assertEqual(
            [(category.key, category.count, category.rate) for category in summaries[self.categorical.id].categories],
            [("a", 2, 1.0), ("b", 1, 0.5), ("c", 0, 0.0)],
        )
        experiment_read = self.service.get_experiment(experiment.id)
        self.assertEqual(experiment_read.visible_scorer_definition_count, 3)
        self.assertEqual(experiment_read.visible_scorer_version_count, 4)

        page = self.service.list_items(experiment.id, OfflineReadQuery(limit=1, scorer_version_ids=(self.numeric.id,)))
        self.assertEqual(page.count, 6)
        summary = self.service.list_summaries(
            experiment.id, OfflineReadQuery(scorer_version_ids=(self.numeric.id,))
        ).results[0]
        self.assertEqual(summary, numeric)

    @parameterized.expand(
        [
            (
                "numeric",
                [
                    {"passing_rule": {"operator": "gte", "threshold": 5}},
                    {"passing_rule": {"operator": "lte", "threshold": 5}},
                ],
                [0.0, 5.0, 10.0, 10.0],
                [3, 2],
            ),
            (
                "categorical",
                [
                    {
                        "options": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}],
                        "selection_mode": "multiple",
                        "passing_rule": {"categories": ["a"]},
                    },
                    {
                        "options": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}],
                        "selection_mode": "multiple",
                        "passing_rule": {"categories": ["a", "b"]},
                    },
                    {
                        "options": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}],
                        "selection_mode": "multiple",
                        "passing_rule": {"categories": []},
                    },
                ],
                [["a"], ["b"], ["a", "b"], ["a"]],
                [2, 4, 0],
            ),
            (
                "boolean",
                [{"true_is_failure": False}, {"true_is_failure": True}],
                [True, False, False, False],
                [1, 3],
            ),
        ]
    )
    def test_passing_summaries_use_pinned_rules_and_exclude_non_scores(
        self, kind: str, configs: list[dict[str, JSONValue]], values: list[ResultValue], pass_counts: list[int]
    ) -> None:
        definition = ScoreDefinition.objects.create(team=self.team, name="Configured scorer", kind=kind)
        versions = [definition.create_new_version(config=config, created_by=None) for config in configs]
        empty_version = definition.create_new_version(config=configs[0], created_by=None)
        unconfigured_version = definition.create_new_version(
            config={"true_is_failure": None} if kind == "boolean" else {**configs[0], "passing_rule": None},
            created_by=None,
        )
        experiment = self._experiment()
        items = [self._item(experiment) for _ in range(8)]
        for version in versions:
            for item, value in zip(items, values):
                self._result(item, version, value)
            for item, status in zip(items[4:7], ("error", "skipped", "not_applicable")):
                self._result(item, version, status=status)
        self._result(items[0], empty_version, status="error")
        self._result(items[0], unconfigured_version, values[0])

        summaries = {
            summary.scorer.id: summary
            for summary in self.service.list_summaries(experiment.id, OfflineReadQuery()).results
        }
        for version, pass_count in zip(versions, pass_counts):
            summary = summaries[version.id]
            self.assertEqual(
                (summary.pass_count, summary.fail_count, summary.pass_rate),
                (pass_count, 4 - pass_count, pass_count / 4),
            )
            self.assertEqual(summary.status_counts, OfflineStatusCounts(ok=4, error=1, skipped=1, not_applicable=1))
            self.assertEqual(summary.missing_result_count, 1)
        empty = summaries[empty_version.id]
        self.assertEqual((empty.pass_count, empty.fail_count, empty.pass_rate), (0, 0, None))
        unconfigured = summaries[unconfigured_version.id]
        self.assertEqual(
            (unconfigured.pass_count, unconfigured.fail_count, unconfigured.pass_rate),
            (1, 0, 1.0) if kind == "boolean" else (None, None, None),
        )
        history = self.service.scorer_history(definition.id, OfflineReadQuery())
        for point in history.results:
            assert point.summary is not None
            self.assertEqual(point.summary, summaries[point.summary.scorer.id])

    @parameterized.expand(
        [
            (1e308, 1e308, 1e308),
            (1e308, -1e308, 0.0),
            (5e-324, 5e-324, 5e-324),
            (float_info.max, float_info.max, float_info.max),
        ]
    )
    def test_numeric_mean_supports_finite_binary64_domain(self, first: float, second: float, expected: float) -> None:
        experiment = self._experiment()
        self._result(self._item(experiment), self.numeric, first)
        self._result(self._item(experiment), self.numeric, second)
        summary = self.service.list_summaries(experiment.id, OfflineReadQuery()).results[0]
        self.assertEqual(summary.mean, expected)

    def test_numeric_mean_rounds_subnormal_underflow_to_zero(self) -> None:
        experiment = self._experiment()
        for value in (5e-324, 0.0, 0.0):
            self._result(self._item(experiment), self.numeric, value)
        summary = self.service.list_summaries(experiment.id, OfflineReadQuery()).results[0]
        self.assertEqual(summary.mean, 0.0)

    def test_experiment_cursor_covers_equal_execution_times_and_is_bound_to_filters(self) -> None:
        experiments = [
            self._experiment(name=f"Run {index}", started_at=self.now - timedelta(days=index // 3))
            for index in range(5)
        ]
        expected = sorted(experiment.id for experiment in experiments[:3]) + sorted(
            experiment.id for experiment in experiments[3:]
        )
        query = OfflineReadQuery(limit=2)
        for offset in range(0, len(expected), query.limit):
            page = self.service.list_experiments(query)
            self.assertEqual(page.count, 5)
            self.assertEqual([experiment.id for experiment in page.results], expected[offset : offset + query.limit])
            if offset + query.limit < len(expected):
                self.assertIsNotNone(page.next_cursor)
                query = replace(query, cursor=page.next_cursor)
            else:
                self.assertIsNone(page.next_cursor)
        with self.assertRaises(OfflineEvaluationValidationError):
            self.service.list_experiments(replace(query, search="Run"))
        older_page = self.service.list_experiments(OfflineReadQuery(limit=2, date_to=self.now))
        self.assertEqual(older_page.count, 2)
        self.assertEqual([experiment.id for experiment in older_page.results], expected[3:])
        self.assertIsNone(older_page.next_cursor)
        self.assertEqual(self.service.get_experiment(expected[0]).id, expected[0])

    def test_model_breakdown_uses_item_overrides_and_group_coverage(self) -> None:
        experiment = self._experiment()
        experiment.model_version = "model-a"
        experiment.save(update_fields=["model_version"])
        inherited = self._item(experiment, case_key="one")
        override = self._item(experiment, case_key="one", model_version="model-b")
        error = self._item(experiment, case_key="two", model_version="model-b")
        self._item(experiment, case_key="missing", model_version="model-b")
        self._result(inherited, self.numeric, 1.0)
        self._result(override, self.numeric, 0.0)
        self._result(error, self.numeric, status="error")
        self._result(inherited, self.boolean, True)
        self._result(override, self.boolean, False)
        self._result(inherited, self.categorical, ["a"])
        self._result(override, self.categorical, ["b"])

        for version in (self.numeric, self.boolean, self.categorical):
            page = self.service.scorer_history(
                version.definition_id, OfflineReadQuery(breakdown=OfflineHistoryBreakdown.MODEL)
            )
            self.assertEqual(page.count, 2)
            groups = {}
            for point in page.results:
                assert point.summary is not None
                groups[point.breakdown_value] = point.summary
            self.assertEqual(groups["model-a"].observed_item_count, 1)
            self.assertEqual(groups["model-b"].observed_item_count, 3)
            self.assertEqual(groups["model-a"].status_counts.ok, 1)
            self.assertEqual(groups["model-b"].status_counts.ok, 1)
            if version == self.numeric:
                self.assertEqual(groups["model-a"].mean, 1.0)
                self.assertEqual(groups["model-b"].mean, 0.0)
                self.assertEqual(groups["model-b"].status_counts.error, 1)
                self.assertEqual(groups["model-b"].missing_result_count, 1)
            elif version == self.boolean:
                self.assertEqual(groups["model-a"].pass_rate, 1.0)
                self.assertEqual(groups["model-b"].pass_rate, 0.0)
            else:
                self.assertEqual([category.rate for category in groups["model-a"].categories], [1.0, 0.0, 0.0])
                self.assertEqual([category.rate for category in groups["model-b"].categories], [0.0, 1.0, 0.0])

        whole = self.service.scorer_history(self.numeric.definition_id, OfflineReadQuery()).results[0].summary
        assert whole is not None
        self.assertEqual((whole.mean, whole.observed_item_count, whole.missing_result_count), (0.5, 4, 1))
        self.assertEqual(self.service.get_item(experiment.id, inherited.id).model_version, "model-a")
        self.assertEqual(self.service.get_item(experiment.id, override.id).model_version, "model-b")

    @parameterized.expand([(None,), (OfflineHistoryBreakdown.MODEL,), (OfflineHistoryBreakdown.SUITE,)])
    def test_model_filter_matches_item_models_across_experiments(
        self, breakdown: OfflineHistoryBreakdown | None
    ) -> None:
        experiments = []
        for index, model in enumerate(("model-a", "model-b")):
            experiment = self._experiment(started_at=self.now - timedelta(hours=index))
            experiment.model_version = model
            experiment.save(update_fields=["model_version"])
            experiments.append(experiment)
            matching_model = None if model == "model-a" else "model-a"
            other_model = "model-b" if model == "model-a" else None
            self._result(self._item(experiment, model_version=matching_model), self.numeric, float(index + 1))
            self._item(experiment, model_version=matching_model)
            self._result(self._item(experiment, model_version=other_model), self.numeric, 100.0)
            self._item(experiment, model_version=other_model)

        query = OfflineReadQuery(model_version="model-a", breakdown=breakdown, limit=1)
        for index, experiment in enumerate(experiments):
            page = self.service.scorer_history(self.numeric.definition_id, query)
            self.assertEqual(page.count, 2)
            self.assertEqual(len(page.results), 1)
            point = page.results[0]
            self.assertEqual(point.experiment.id, experiment.id)
            self.assertEqual(point.breakdown_value, "model-a" if breakdown == OfflineHistoryBreakdown.MODEL else None)
            assert point.summary is not None
            self.assertEqual(point.summary.mean, float(index + 1))
            self.assertEqual(point.summary.status_counts.ok, 1)
            self.assertEqual(point.summary.observed_item_count, 2)
            self.assertEqual(point.summary.missing_result_count, 1)
            self.assertEqual(page.next_cursor is None, index == 1)
            query = replace(query, cursor=page.next_cursor)

        listed = self.service.list_experiments(OfflineReadQuery(model_version="model-a"))
        self.assertEqual([experiment.id for experiment in listed.results], [experiments[0].id])

    def test_model_breakdown_paginates_missing_and_named_models_without_duplicates(self) -> None:
        experiment = self._experiment()
        models = [None, "model-a", "model-b", "Not specified", "模" * 255, "😀" * 255, "😁" * 255]
        for index, model in enumerate(models):
            self._result(self._item(experiment, model_version=model, case_key="scored"), self.numeric, 1.0)
            for missing in range(index + 1):
                self._item(experiment, model_version=model, case_key=f"missing-{missing}")
        query = OfflineReadQuery(breakdown=OfflineHistoryBreakdown.MODEL, limit=1)
        values = []
        while True:
            page = self.service.scorer_history(self.numeric.definition_id, query)
            self.assertEqual(page.count, len(models))
            self.assertEqual(len(page.results), 1)
            point = page.results[0]
            values.append(point.breakdown_value)
            missing_count = models.index(point.breakdown_value) + 1
            assert point.summary is not None
            self.assertEqual(point.summary.observed_item_count, missing_count + 1)
            self.assertEqual(point.summary.distinct_case_count, missing_count + 1)
            self.assertEqual(point.summary.missing_result_count, missing_count)
            if not page.next_cursor:
                break
            serializer = OfflineScorerHistoryQuerySerializer(
                data={"breakdown": "model_version", "limit": 1, "cursor": page.next_cursor}
            )
            self.assertTrue(serializer.is_valid(), serializer.errors)
            with self.assertRaises(OfflineEvaluationValidationError):
                self.service.scorer_history(
                    self.numeric.definition_id,
                    replace(query, cursor=page.next_cursor, breakdown=OfflineHistoryBreakdown.SUITE),
                )
            query = replace(query, cursor=page.next_cursor)
        self.assertCountEqual(values, models)

    @parameterized.expand(
        [
            (OfflineHistoryBreakdown.PROMPT, "prompt-a"),
            (OfflineHistoryBreakdown.APPLICATION, "build-a"),
            (OfflineHistoryBreakdown.SUITE, "suite-a"),
            (OfflineHistoryBreakdown.SOURCE, "ci"),
        ]
    )
    def test_experiment_breakdowns_keep_all_items_in_one_group(
        self, breakdown: OfflineHistoryBreakdown, value: str
    ) -> None:
        experiment = self._experiment()
        setattr(experiment, breakdown, value)
        experiment.save(update_fields=[breakdown])
        for model in ("model-a", "model-b"):
            self._result(self._item(experiment, model_version=model), self.numeric, 1.0)
        page = self.service.scorer_history(self.numeric.definition_id, OfflineReadQuery(breakdown=breakdown))
        self.assertEqual(page.count, 1)
        self.assertEqual(page.results[0].breakdown_value, value)
        assert page.results[0].summary is not None
        self.assertEqual(page.results[0].summary.observed_item_count, 2)

    def test_history_pages_experiment_version_groups_by_execution_time(self) -> None:
        older = self._experiment(started_at=self.now - timedelta(days=5), run_source="ci")
        newer = self._experiment(run_source="local")
        uploading = self._experiment(status="uploading")
        for experiment in (older, newer, uploading):
            item = self._item(experiment)
            self._result(item, self.numeric, 1.0)
            self._result(item, self.numeric_v2, 2.0)
        expected = [
            (experiment.id, version_id)
            for experiment in (newer, older)
            for version_id in sorted((self.numeric.id, self.numeric_v2.id))
        ]
        seen = []
        query = OfflineReadQuery(limit=1)
        while True:
            page = self.service.scorer_history(self.numeric.definition_id, query)
            self.assertEqual(page.count, 4)
            point = page.results[0]
            assert point.summary is not None
            seen.append((point.experiment.id, point.summary.scorer.id))
            self.assertEqual(
                point.summary,
                self.service.list_summaries(
                    point.experiment.id, OfflineReadQuery(scorer_version_ids=(point.summary.scorer.id,))
                ).results[0],
            )
            if page.next_cursor is None:
                break
            query = replace(query, cursor=page.next_cursor)
        self.assertEqual(seen, expected)
        self.assertEqual(
            self.service.scorer_history(
                self.numeric.definition_id, OfflineReadQuery(statuses=("completed", "uploading"))
            ).count,
            6,
        )
        self.assertEqual(
            self.service.scorer_history(self.numeric.definition_id, OfflineReadQuery(run_source="ci")).count, 2
        )
        self.assertEqual(
            self.service.scorer_history(self.numeric.definition_id, OfflineReadQuery(run_source_is_null=True)).count, 0
        )
        with self.assertRaises(OfflineEvaluationNotFound):
            self.service.scorer_history(
                self.numeric.definition_id, OfflineReadQuery(scorer_version_ids=(self.boolean.id,))
            )

    def test_items_with_missing_selected_scores_stay_visible_and_result_pages_are_bounded(self) -> None:
        experiment = self._experiment()
        first, missing = self._item(experiment), self._item(experiment)
        self._result(first, self.numeric, 1.0)
        self._result(first, self.numeric_v2, 2.0)
        self._result(first, self.boolean, False)
        query = OfflineReadQuery(scorer_version_ids=(self.categorical.id, self.numeric.id))
        items = self.service.list_items(experiment.id, query)
        self.assertEqual(items.count, 2)
        self.assertEqual({item.id: len(item.results) for item in items.results}, {first.id: 1, missing.id: 0})
        self.assertEqual([scorer.id for scorer in items.scorer_versions], sorted(query.scorer_version_ids))
        versions = {scorer.id: scorer for scorer in items.scorer_versions}
        self.assertEqual(versions[self.categorical.id].config, self.categorical.config)
        result = next(item for item in items.results if item.id == first.id).results[0]
        self.assertEqual((result.scorer.id, result.value), (self.numeric.id, 1.0))
        empty = self.service.list_items(self._experiment().id, query)
        self.assertEqual((empty.count, empty.results), (0, []))
        self.assertEqual(empty.scorer_versions, items.scorer_versions)
        unselected = self.service.list_items(experiment.id, OfflineReadQuery())
        self.assertEqual(unselected.scorer_versions, [])
        self.assertTrue(all(not item.results for item in unselected.results))
        self.assertEqual(self.service.get_item(experiment.id, first.id).results, [])
        first_page = self.service.list_item_results(experiment.id, first.id, OfflineReadQuery(limit=2))
        self.assertEqual((first_page.count, len(first_page.results)), (3, 2))
        second_page = self.service.list_item_results(
            experiment.id, first.id, OfflineReadQuery(limit=2, cursor=first_page.next_cursor)
        )
        self.assertEqual(len(second_page.results), 1)
        self.assertEqual(len({result.id for result in first_page.results + second_page.results}), 3)
        self.assertEqual(
            {result.scorer.id for result in first_page.results + second_page.results},
            {self.numeric.id, self.numeric_v2.id, self.boolean.id},
        )

    def test_payload_states_survive_independent_expiry_without_changing_summaries(self) -> None:
        experiment = self._experiment()
        item = self._item(experiment)
        result = self._result(item, self.numeric, 1.0)
        absent = self.service.get_item_payload(experiment.id, item.id)
        self.assertEqual((absent.payload_state, absent.available, absent.data), ("not_provided", False, None))
        item.accepted_at = self.now - timedelta(days=31)
        item.save(update_fields=["accepted_at"])
        self._payload(item, {"input": None})
        self._payload(result, {})
        self.assertEqual(self.service.get_item_payload(experiment.id, item.id).payload_state, "available")
        self.assertEqual(self.service.get_item_payload(experiment.id, item.id).data, {"input": None})
        self.assertEqual(
            self.service.list_items(experiment.id, OfflineReadQuery()).results[0].payload_state, "available"
        )
        self.assertEqual(self.service.get_result_payload(experiment.id, result.id).data, {})
        before = self.service.list_summaries(experiment.id, OfflineReadQuery())
        OfflinePayloadRetention().run()
        expired = self.service.get_item_payload(experiment.id, item.id)
        self.assertEqual((expired.payload_state, expired.available, expired.data), ("expired", False, None))
        self.assertEqual(self.service.list_items(experiment.id, OfflineReadQuery()).results[0].payload_state, "expired")
        self.assertTrue(self.service.get_result_payload(experiment.id, result.id).available)
        self.assertEqual(self.service.list_summaries(experiment.id, OfflineReadQuery()), before)
        self.assertEqual(
            self.service.scorer_history(self.numeric.definition_id, OfflineReadQuery()).results[0].summary,
            before.results[0],
        )
        result.accepted_at = item.accepted_at
        result.payload_expires_at = item.payload_expires_at
        result.save(update_fields=["accepted_at", "payload_expires_at"])
        self.assertEqual(self.service.get_result_payload(experiment.id, result.id).data, {})
        OfflinePayloadRetention().run()
        expired_result = self.service.get_result_payload(experiment.id, result.id)
        self.assertEqual(
            (expired_result.payload_state, expired_result.available, expired_result.data), ("expired", False, None)
        )

    def test_metadata_only_counts_and_nested_identity_checks(self) -> None:
        experiment, other_experiment = self._experiment(), self._experiment()
        item = self._item(experiment)
        result = self._result(item, self.numeric, 1.0)
        metadata = OfflineEvaluationReadService(team_id=self.team.id, user_access_control=None, can_read_scores=False)
        read = metadata.get_experiment(experiment.id)
        self.assertEqual(read.accepted_item_count, 1)
        self.assertEqual(read.result_count_scope, "unavailable")
        self.assertIsNone(read.visible_result_count)
        self.assertIsNone(read.visible_scorer_definition_count)
        self.assertIsNone(read.visible_scorer_version_count)
        with self.assertRaises(OfflineEvaluationNotFound):
            metadata.list_items(experiment.id, OfflineReadQuery(scorer_version_ids=(self.numeric.id,)))
        with self.assertRaises(OfflineEvaluationNotFound):
            self.service.get_item_payload(other_experiment.id, item.id)
        with self.assertRaises(OfflineEvaluationNotFound):
            self.service.get_result_payload(other_experiment.id, result.id)
        other_service = OfflineEvaluationReadService(
            team_id=self.other_team.id, user_access_control=None, can_read_scores=True
        )
        self.assertEqual(other_service.list_experiments(OfflineReadQuery()).count, 0)
        with self.assertRaises(OfflineEvaluationNotFound):
            other_service.get_item(experiment.id, item.id)

    def test_page_queries_remain_bounded_and_do_not_load_payloads(self) -> None:
        for _ in range(5):
            experiment = self._experiment()
            item = self._item(experiment)
            self._payload(item, {"input": "A bounded synthetic input"})
            self._result(item, self.numeric, 1.0)
        with CaptureQueriesContext(connection) as small:
            self.service.list_experiments(OfflineReadQuery(limit=1))
        with CaptureQueriesContext(connection) as large:
            self.service.list_experiments(OfflineReadQuery(limit=100))
        self.assertEqual(len(small), len(large))
        with CaptureQueriesContext(connection) as history:
            self.service.scorer_history(self.numeric.definition_id, OfflineReadQuery())
        for query in [*large.captured_queries, *history.captured_queries]:
            self.assertNotIn("offlineexperimentitempayload", query["sql"])
            self.assertNotIn("offlineevaluationresultpayload", query["sql"])
