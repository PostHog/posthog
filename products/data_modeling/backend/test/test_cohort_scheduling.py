from datetime import timedelta

from unittest import TestCase

from parameterized import parameterized

from products.data_modeling.backend.logic.cohort_scheduling import (
    Tier,
    bucket_into_cadence_tiers,
    dag_id_from_schedule_id,
    format_tier,
    interval_seconds_from_schedule_id,
    plan_schedule_reconciliation,
    tier_schedule_id,
    tier_sort_key,
)

DAG_ID = "018f2a00-0000-0000-0000-000000000000"
M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
H6 = timedelta(hours=6)
H24 = timedelta(hours=24)


class TestBucketIntoCadenceTiers(TestCase):
    def test_groups_by_interval_and_drops_unscheduled(self):
        effective = {"a": M15, "b": M15, "c": H1, "d": None}
        self.assertEqual(bucket_into_cadence_tiers(effective), {Tier(M15): {"a", "b"}, Tier(H1): {"c"}})

    def test_empty_graph_has_no_tiers(self):
        self.assertEqual(bucket_into_cadence_tiers({}), {})

    def test_anchored_nodes_split_from_hash_spread_cohort(self):
        effective = {"a": H24, "b": H24, "c": H24, "d": None}
        anchors = {"b": 0, "c": 0, "d": 0}
        self.assertEqual(
            bucket_into_cadence_tiers(effective, anchors),
            {Tier(H24): {"a"}, Tier(H24, 0): {"b", "c"}},
        )

    def test_different_anchors_are_different_cohorts(self):
        effective: dict[str, timedelta | None] = {"a": H24, "b": H24}
        self.assertEqual(
            bucket_into_cadence_tiers(effective, {"a": 0, "b": 360}),
            {Tier(H24, 0): {"a"}, Tier(H24, 360): {"b"}},
        )

    @parameterized.expand(
        [
            # the spec ignores the day part below weekly, so anchors equal mod the cadence are
            # one cohort — otherwise `--on tuesday` on a mixed daily+weekly selection splits
            # daily nodes into a second schedule that fires identically
            ("daily_day_part_inert", H24, {"a": 0, "b": 1440}, Tier(H24, 0)),
            ("sub_daily_phase_mod_interval", H6, {"a": 1350, "b": 270}, Tier(H6, 270)),
            ("weekly_keeps_full_offset", timedelta(days=7), {"a": 4380, "b": 4380}, Tier(timedelta(days=7), 4380)),
            ("monthly_time_of_day_only", timedelta(days=30), {"a": 1500, "b": 60}, Tier(timedelta(days=30), 60)),
        ]
    )
    def test_equivalent_anchors_collapse_into_one_cohort(self, _name, interval, anchors, expected_tier):
        effective: dict[str, timedelta | None] = {"a": interval, "b": interval}
        self.assertEqual(bucket_into_cadence_tiers(effective, anchors), {expected_tier: {"a", "b"}})


class TestTierScheduleId(TestCase):
    @parameterized.expand(
        [
            ("unanchored", None, f"{DAG_ID}:900", 900),
            ("anchored", 120, f"{DAG_ID}:900:120", 900),
        ]
    )
    def test_round_trip(self, _name, anchor, expected_id, expected_seconds):
        schedule_id = tier_schedule_id(DAG_ID, M15, anchor)
        self.assertEqual(schedule_id, expected_id)
        self.assertEqual(dag_id_from_schedule_id(schedule_id), DAG_ID)
        self.assertEqual(interval_seconds_from_schedule_id(schedule_id), expected_seconds)

    def test_pre_tier_schedule_id_parses_to_itself(self):
        # migration-era schedules use the bare dag id (no colon); the read side must still resolve it
        self.assertEqual(dag_id_from_schedule_id(DAG_ID), DAG_ID)
        self.assertIsNone(interval_seconds_from_schedule_id(DAG_ID))


class TestTierDisplay(TestCase):
    def test_sort_key_orders_hash_spread_before_anchored_within_a_cadence(self):
        tiers = [Tier(H24, 0), Tier(H24), Tier(M15)]
        self.assertEqual(sorted(tiers, key=tier_sort_key), [Tier(M15), Tier(H24), Tier(H24, 0)])

    @parameterized.expand(
        [
            # only weekly gets a weekday: sub-weekly specs ignore the day part, and monthly's
            # day of month is hash-picked — naming a day there tells the operator a fire
            # calendar the schedule does not have
            ("unanchored", Tier(H24), "1day"),
            ("midnight", Tier(H24, 0), "1day@00:00"),
            ("daily_time_only", Tier(H24, 1350), "1day@22:30"),
            ("sub_daily_phase", Tier(H6, 1350), "6hour@04:30"),
            ("weekly_tuesday", Tier(timedelta(days=7), 1560), "7day@tue 02:00"),
            ("monthly_time_only", Tier(timedelta(days=30), 1560), "30day@02:00"),
        ]
    )
    def test_format_tier(self, _name, tier, expected):
        self.assertEqual(format_tier(tier), expected)


class TestPlanScheduleReconciliation(TestCase):
    def test_splits_into_create_update_and_delete(self):
        desired = {Tier(M15): {"a"}, Tier(H1): {"b", "c"}}
        existing = {tier_schedule_id(DAG_ID, H1), tier_schedule_id(DAG_ID, H6)}
        plan = plan_schedule_reconciliation(DAG_ID, desired, existing)
        self.assertEqual(plan.to_create, {tier_schedule_id(DAG_ID, M15): (Tier(M15), {"a"})})
        self.assertEqual(plan.to_update, {tier_schedule_id(DAG_ID, H1): (Tier(H1), {"b", "c"})})
        self.assertEqual(plan.to_delete, {tier_schedule_id(DAG_ID, H6)})

    def test_migration_era_single_schedule_is_swept_into_delete(self):
        # a DAG still on the old bare-dag-id schedule gets it deleted and replaced by tiers
        plan = plan_schedule_reconciliation(DAG_ID, {Tier(M15): {"a"}}, {DAG_ID})
        self.assertEqual(plan.to_create, {tier_schedule_id(DAG_ID, M15): (Tier(M15), {"a"})})
        self.assertEqual(plan.to_update, {})
        self.assertEqual(plan.to_delete, {DAG_ID})

    def test_removing_last_target_deletes_all_schedules(self):
        existing = {tier_schedule_id(DAG_ID, M15), tier_schedule_id(DAG_ID, H1)}
        plan = plan_schedule_reconciliation(DAG_ID, {}, existing)
        self.assertEqual(plan.to_create, {})
        self.assertEqual(plan.to_update, {})
        self.assertEqual(plan.to_delete, existing)

    def test_anchored_and_unanchored_same_cadence_are_distinct_schedules(self):
        # keying schedules by interval alone would collide these two cohorts,
        # silently merging a pinned phase with the hash-spread one
        desired = {Tier(H24): {"a"}, Tier(H24, 0): {"b"}}
        plan = plan_schedule_reconciliation(DAG_ID, desired, set())
        self.assertEqual(
            set(plan.to_create),
            {tier_schedule_id(DAG_ID, H24), tier_schedule_id(DAG_ID, H24, 0)},
        )

    def test_clearing_an_anchor_sweeps_the_anchored_schedule(self):
        existing = {tier_schedule_id(DAG_ID, H24, 0)}
        plan = plan_schedule_reconciliation(DAG_ID, {Tier(H24): {"a"}}, existing)
        self.assertEqual(set(plan.to_create), {tier_schedule_id(DAG_ID, H24)})
        self.assertEqual(plan.to_delete, existing)
