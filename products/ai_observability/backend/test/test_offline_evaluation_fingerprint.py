from dataclasses import replace
from datetime import datetime
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.api.offline_experiment_serializers import ResultSubmissionSerializer
from products.ai_observability.backend.offline_evaluation_fingerprint import submission_fingerprint
from products.ai_observability.backend.offline_evaluation_types import ExperimentSubmission, ItemSubmission, JSONValue

ITEM_ID = UUID("01922222-2222-7222-8222-222222222222")
SCORER_VERSION_ID = UUID("01923333-3333-7333-8333-333333333333")


class TestOfflineEvaluationFingerprint(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "nested_object_order",
                {"input": {"question": "Hello", "context": ["A", "B"]}, "output": "World"},
                {"output": "World", "input": {"context": ["A", "B"], "question": "Hello"}},
            ),
            ("integer_and_whole_float", {"input": [1, {"count": 2}]}, {"input": [1.0, {"count": 2.0}]}),
            ("negative_zero", {"input": -0.0}, {"input": 0}),
        ]
    )
    def test_equivalent_payloads_have_the_same_fingerprint(
        self, _name: str, first: dict[str, JSONValue], second: dict[str, JSONValue]
    ) -> None:
        self.assertEqual(
            submission_fingerprint(ItemSubmission(id=ITEM_ID, payload=first)),
            submission_fingerprint(ItemSubmission(id=ITEM_ID, payload=second)),
        )

    @parameterized.expand(
        [
            ("omitted_and_empty", None, {}),
            ("empty_and_null_property", {}, {"input": None}),
            ("array_order", {"input": ["A", "B"]}, {"input": ["B", "A"]}),
            ("boolean_and_number", {"input": True}, {"input": 1}),
        ]
    )
    def test_distinct_payloads_have_different_fingerprints(
        self, _name: str, first: dict[str, JSONValue] | None, second: dict[str, JSONValue] | None
    ) -> None:
        self.assertNotEqual(
            submission_fingerprint(ItemSubmission(id=ITEM_ID, payload=first)),
            submission_fingerprint(ItemSubmission(id=ITEM_ID, payload=second)),
        )

    def test_equivalent_timestamp_offsets_have_the_same_fingerprint(self) -> None:
        submission = ExperimentSubmission(
            id=ITEM_ID, name="Candidate model", started_at=datetime.fromisoformat("2026-09-24T10:00:00+00:00")
        )
        self.assertEqual(
            submission_fingerprint(submission),
            submission_fingerprint(replace(submission, started_at=datetime.fromisoformat("2026-09-24T06:00:00-04:00"))),
        )

    def test_serialized_category_order_has_the_same_fingerprint(self) -> None:
        fingerprints = []
        for values in (["accurate", "helpful"], ["helpful", "accurate"]):
            serializer = ResultSubmissionSerializer(
                data={
                    "item_id": str(ITEM_ID),
                    "scorer_version_id": str(SCORER_VERSION_ID),
                    "status": "ok",
                    "value": values,
                }
            )
            self.assertTrue(serializer.is_valid(), serializer.errors)
            fingerprints.append(submission_fingerprint(serializer.validated_data))
        self.assertEqual(fingerprints[0], fingerprints[1])
