from datetime import timedelta

from unittest import TestCase

from products.data_modeling.backend.logic.cohort_scheduling import (
    bucket_into_cadence_tiers,
    dag_id_from_schedule_id,
    plan_schedule_reconciliation,
    tier_schedule_id,
)

DAG_ID = "018f2a00-0000-0000-0000-000000000000"
M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
H6 = timedelta(hours=6)


class TestBucketIntoCadenceTiers(TestCase):
    def test_groups_by_interval_and_drops_unscheduled(self):
        effective = {"a": M15, "b": M15, "c": H1, "d": None}
        self.assertEqual(bucket_into_cadence_tiers(effective), {M15: {"a", "b"}, H1: {"c"}})

    def test_empty_graph_has_no_tiers(self):
        self.assertEqual(bucket_into_cadence_tiers({}), {})


class TestTierScheduleId(TestCase):
    def test_round_trip(self):
        schedule_id = tier_schedule_id(DAG_ID, M15)
        self.assertEqual(schedule_id, f"{DAG_ID}:900")
        self.assertEqual(dag_id_from_schedule_id(schedule_id), DAG_ID)

    def test_pre_tier_schedule_id_parses_to_itself(self):
        # migration-era schedules use the bare dag id (no colon); the read side must still resolve it
        self.assertEqual(dag_id_from_schedule_id(DAG_ID), DAG_ID)


class TestPlanScheduleReconciliation(TestCase):
    def test_splits_into_create_update_and_delete(self):
        desired = {M15: {"a"}, H1: {"b", "c"}}
        existing = {tier_schedule_id(DAG_ID, H1), tier_schedule_id(DAG_ID, H6)}
        plan = plan_schedule_reconciliation(DAG_ID, desired, existing)
        self.assertEqual(plan.to_create, {tier_schedule_id(DAG_ID, M15): (M15, {"a"})})
        self.assertEqual(plan.to_update, {tier_schedule_id(DAG_ID, H1): (H1, {"b", "c"})})
        self.assertEqual(plan.to_delete, {tier_schedule_id(DAG_ID, H6)})

    def test_migration_era_single_schedule_is_swept_into_delete(self):
        # a DAG still on the old bare-dag-id schedule gets it deleted and replaced by tiers
        plan = plan_schedule_reconciliation(DAG_ID, {M15: {"a"}}, {DAG_ID})
        self.assertEqual(plan.to_create, {tier_schedule_id(DAG_ID, M15): (M15, {"a"})})
        self.assertEqual(plan.to_update, {})
        self.assertEqual(plan.to_delete, {DAG_ID})

    def test_removing_last_target_deletes_all_schedules(self):
        existing = {tier_schedule_id(DAG_ID, M15), tier_schedule_id(DAG_ID, H1)}
        plan = plan_schedule_reconciliation(DAG_ID, {}, existing)
        self.assertEqual(plan.to_create, {})
        self.assertEqual(plan.to_update, {})
        self.assertEqual(plan.to_delete, existing)
