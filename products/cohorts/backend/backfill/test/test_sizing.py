from datetime import UTC, datetime

from unittest import mock

from django.test import SimpleTestCase, override_settings

from products.cohorts.backend.backfill.sizing import estimate_person_seed_topic_bytes


@override_settings(BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=10_000)
class TestPersonBackfillSizing(SimpleTestCase):
    @mock.patch(
        "products.cohorts.backend.backfill.sizing.sync_execute",
        return_value=[(10,)],
    )
    def test_estimate_counts_both_worst_case_hash_vectors(self, sync_execute: mock.Mock) -> None:
        person_scan_since = datetime(2026, 5, 1, tzinfo=UTC)

        estimate = estimate_person_seed_topic_bytes(7, person_scan_since, 2)

        self.assertEqual(estimate.estimated_persons, 10)
        self.assertEqual(estimate.bytes_per_seed, 332)
        self.assertEqual(estimate.estimated_topic_bytes, 3_320)
        self.assertEqual(estimate.budget_bytes, 10_000)
        self.assertFalse(estimate.over_budget)
        self.assertEqual(
            estimate.as_preconditions(),
            {
                "person_seed_estimated_persons": 10,
                "person_seed_pinned_condition_count": 2,
                "person_seed_bytes_per_seed": 332,
                "person_seed_estimated_topic_bytes": 3_320,
                "person_seed_topic_bytes_budget": 10_000,
            },
        )
        # Deleted persons must not inflate the estimate, and the read has to be byte-bounded so the
        # gate throws instead of sizing a run off a partial scan. Neither is observable without CH.
        self.assertIn("is_deleted", sync_execute.call_args.args[0])
        self.assertEqual(
            sync_execute.call_args.args[1],
            {"team_id": 7, "person_scan_since": person_scan_since},
        )
        self.assertEqual(
            sync_execute.call_args.kwargs["settings"],
            {"max_execution_time": 30, "max_bytes_to_read": 10_000_000_000, "read_overflow_mode": "throw"},
        )
        self.assertEqual(sync_execute.call_args.kwargs["team_id"], 7)
        self.assertTrue(sync_execute.call_args.kwargs["readonly"])
