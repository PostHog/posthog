from dataclasses import replace
from datetime import datetime, timedelta
from sys import float_info
from uuid import UUID, uuid4

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

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
    OfflineReadQuery,
    OfflineStatusCounts,
    decode_cursor,
    encode_cursor,
)
from products.ai_observability.backend.offline_evaluation_service import (
    OfflineEvaluationNotFound,
    OfflineEvaluationValidationError,
)
from products.ai_observability.backend.offline_evaluation_types import JSONValue, ResultValue


class TestOfflineReadQuery(SimpleTestCase):
    @parameterized.expand([("!",), ("a" * 2049,), (encode_cursor(["id", "extra"]),), ("bnVsbA",)])
    def test_rejects_malformed_or_wrong_shape_cursor(self, cursor: str) -> None:
        with self.assertRaises(OfflineEvaluationValidationError):
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
        self, experiment: OfflineExperiment, *, case_key: str | None = None, trial: str | None = None
    ) -> OfflineExperimentItem:
        return OfflineExperimentItem.objects.for_team(self.team.id).create(
            id=uuid4(),
            team=self.team,
            experiment=experiment,
            case_key=case_key,
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
        experiments = [self._experiment(name=f"Run {index}") for index in range(5)]
        expected = sorted(experiment.id for experiment in experiments)
        seen: list[UUID] = []
        query = OfflineReadQuery(limit=2)
        while True:
            page = self.service.list_experiments(query)
            self.assertEqual(page.count, 5)
            seen.extend(experiment.id for experiment in page.results)
            if page.next_cursor is None:
                break
            query = replace(query, cursor=page.next_cursor)
        self.assertEqual(seen, expected)
        with self.assertRaises(OfflineEvaluationValidationError):
            self.service.list_experiments(replace(query, search="Run"))
        self.assertEqual(self.service.list_experiments(OfflineReadQuery(date_to=self.now)).count, 0)
        self.assertEqual(self.service.get_experiment(expected[0]).id, expected[0])

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

    def test_items_with_missing_selected_scores_stay_visible_and_result_pages_are_bounded(self) -> None:
        experiment = self._experiment()
        first, missing = self._item(experiment), self._item(experiment)
        self._result(first, self.numeric, 1.0)
        self._result(first, self.numeric_v2, 2.0)
        self._result(first, self.boolean, False)
        items = self.service.list_items(experiment.id, OfflineReadQuery(scorer_version_ids=(self.numeric.id,)))
        self.assertEqual(items.count, 2)
        self.assertEqual({item.id: len(item.results) for item in items.results}, {first.id: 1, missing.id: 0})
        self.assertEqual(self.service.get_item(experiment.id, first.id).results, [])
        first_page = self.service.list_item_results(experiment.id, first.id, OfflineReadQuery(limit=2))
        self.assertEqual((first_page.count, len(first_page.results)), (3, 2))
        second_page = self.service.list_item_results(
            experiment.id, first.id, OfflineReadQuery(limit=2, cursor=first_page.next_cursor)
        )
        self.assertEqual(len(second_page.results), 1)
        self.assertEqual(len({result.id for result in first_page.results + second_page.results}), 3)

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
        self.assertEqual(self.service.get_item_payload(experiment.id, item.id).data, {"input": None})
        self.assertEqual(self.service.get_result_payload(experiment.id, result.id).data, {})
        before = self.service.list_summaries(experiment.id, OfflineReadQuery())
        OfflineExperimentItemPayload.objects.for_team(self.team.id).filter(item_id=item.id).delete()
        item.payload_state = PayloadState.EXPIRED
        item.save(update_fields=["payload_state"])
        expired = self.service.get_item_payload(experiment.id, item.id)
        self.assertEqual((expired.payload_state, expired.available, expired.data), ("expired", False, None))
        self.assertTrue(self.service.get_result_payload(experiment.id, result.id).available)
        self.assertEqual(self.service.list_summaries(experiment.id, OfflineReadQuery()), before)
        self.assertEqual(
            self.service.scorer_history(self.numeric.definition_id, OfflineReadQuery()).results[0].summary,
            before.results[0],
        )

    def test_metadata_only_counts_and_nested_identity_checks(self) -> None:
        experiment, other_experiment = self._experiment(), self._experiment()
        item = self._item(experiment)
        result = self._result(item, self.numeric, 1.0)
        metadata = OfflineEvaluationReadService(team_id=self.team.id, user_access_control=None, can_read_scores=False)
        read = metadata.get_experiment(experiment.id)
        self.assertEqual(read.accepted_item_count, 1)
        self.assertFalse(read.result_counts_available)
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
