from datetime import timedelta

from unittest import TestCase

from parameterized import parameterized

from products.data_modeling.backend.logic.freshness import (
    SCHEDULABLE_BUCKETS,
    STREAMING,
    InvalidTarget,
    UnsatisfiableFrequencyError,
    UnsupportedFrequencyTargetError,
    all_consumer_ceilings,
    all_source_floors,
    clamp_to_source_floor,
    compute_effective_cadences,
    find_invalid_targets,
    normalize_seed_target,
    validate_declared_target,
)

M5 = timedelta(minutes=5)
M15 = timedelta(minutes=15)
M30 = timedelta(minutes=30)
M45 = timedelta(minutes=45)
H1 = timedelta(hours=1)
H6 = timedelta(hours=6)
DAY = timedelta(days=1)


class TestComputeEffectiveCadences(TestCase):
    @parameterized.expand(
        [
            # chain src->a->b: a with no target inherits b's target
            ("chain_inherits", {"a", "b"}, [("src", "a"), ("a", "b")], {"b": H1}, {"a": H1, "b": H1}),
            # diamond: shared parent mA takes the tightest of its two consumers
            (
                "diamond_takes_tightest_child",
                {"mA", "epA", "epB"},
                [("src", "mA"), ("mA", "epA"), ("mA", "epB")],
                {"epA": H1, "epB": M15},
                {"mA": M15, "epA": H1, "epB": M15},
            ),
            # own target tighter than children wins (you may be more frequent than consumers need)
            (
                "own_target_tighter_than_children",
                {"mA", "epA", "epB"},
                [("mA", "epA"), ("mA", "epB")],
                {"mA": M5, "epA": H1, "epB": M15},
                {"mA": M5, "epA": H1, "epB": M15},
            ),
            # transitive demand propagates past an intermediate node with no target
            (
                "transitive_two_levels",
                {"a", "b", "c", "d"},
                [("src", "a"), ("a", "b"), ("b", "c"), ("b", "d")],
                {"c": M15, "d": H1},
                {"a": M15, "b": M15, "c": M15, "d": H1},
            ),
            # a leaf with no target and no consumers is unscheduled; its None must not poison the parent
            (
                "unscheduled_leaf_is_none",
                {"a", "b"},
                [("a", "b")],
                {"a": H1},
                {"a": H1, "b": None},
            ),
        ]
    )
    def test_effective_cadence(self, _name, nodes, edges, targets, expected):
        self.assertEqual(compute_effective_cadences(nodes=nodes, edges=edges, declared_targets=targets), expected)

    def test_deep_chain_does_not_overflow(self):
        # prod DAGs can chain far past Python's recursion limit; propagation must stay iterative
        depth = 5000
        nodes = {f"n{i}" for i in range(depth)}
        edges = [(f"n{i}", f"n{i + 1}") for i in range(depth - 1)]
        result = compute_effective_cadences(nodes=nodes, edges=edges, declared_targets={f"n{depth - 1}": H1})
        self.assertEqual(result["n0"], H1)

    def test_cycle_raises_instead_of_hanging(self):
        # corrupt graphs exist in prod; a cycle must fail loud, not loop or overflow
        with self.assertRaisesRegex(ValueError, "cycle"):
            compute_effective_cadences(nodes={"a", "b"}, edges=[("a", "b"), ("b", "a")], declared_targets={"a": H1})


class TestValidateFrequencyTarget(TestCase):
    @parameterized.expand(
        [
            # in range against a streamed source -> ok
            ("streamed_15min_ok", "a", M15, [("src", "a"), ("a", "ep")], {"ep": M15}, {"src": STREAMING}, True),
            # fresher than an imported source can deliver -> rejected
            ("below_imported_floor", "a", M15, [("src", "a")], {}, {"src": H6}, False),
            # staler than a downstream consumer needs -> rejected
            ("above_descendant_ceiling", "a", DAY, [("a", "ep")], {"ep": M15}, {}, False),
            # exactly on an imported floor -> ok
            ("on_imported_floor_ok", "a", H6, [("src", "a")], {}, {"src": H6}, True),
            # exactly on a descendant ceiling -> ok (bounds are inclusive at both ends)
            ("on_descendant_ceiling_ok", "a", M15, [("a", "ep")], {"ep": M15}, {}, True),
            # floor 6h > ceiling 15min: no target is accepted, at either end of the range
            ("unsatisfiable_rejects_floor_end", "a", H6, [("src", "a"), ("a", "ep")], {"ep": M15}, {"src": H6}, False),
            (
                "unsatisfiable_rejects_ceiling_end",
                "a",
                M15,
                [("src", "a"), ("a", "ep")],
                {"ep": M15},
                {"src": H6},
                False,
            ),
        ]
    )
    def test_validate(self, _name, node_id, target, edges, targets, source_intervals, ok):
        if ok:
            validate_declared_target(
                node_id=node_id, target=target, edges=edges, declared_targets=targets, source_intervals=source_intervals
            )
        else:
            with self.assertRaises(UnsatisfiableFrequencyError):
                validate_declared_target(
                    node_id=node_id,
                    target=target,
                    edges=edges,
                    declared_targets=targets,
                    source_intervals=source_intervals,
                )

    @parameterized.expand(
        [
            # 45min would silently degrade to hourly in the spec builder
            ("non_divisor_of_hour", timedelta(minutes=45)),
            # sub-minute would crash the spec builder with a zero-division
            ("sub_minute", timedelta(seconds=30)),
        ]
    )
    def test_non_bucket_target_is_rejected(self, _name, target):
        with self.assertRaises(UnsupportedFrequencyTargetError):
            validate_declared_target(node_id="a", target=target, edges=[], declared_targets={}, source_intervals={})

    def test_supported_targets_are_canonical_sync_frequency_buckets(self):
        from products.warehouse_sources.backend.facade.models import (  # noqa: PLC0415 - keeps Django off this pure test module's import path
            sync_frequency_interval_to_sync_frequency,
            sync_frequency_to_sync_frequency_interval,
        )

        for interval in SCHEDULABLE_BUCKETS:
            label = sync_frequency_interval_to_sync_frequency(interval)
            self.assertIsNotNone(label, f"{interval} is not a canonical sync-frequency bucket")
            assert label is not None
            self.assertEqual(sync_frequency_to_sync_frequency_interval(label), interval)


class TestFindInvalidTargets(TestCase):
    @parameterized.expand(
        [
            # descendant's 15min target lowers the ancestor's ceiling below its declared 6h
            (
                "ancestor_invalidated_by_descendant_target",
                [("src", "a"), ("a", "ep")],
                {"a": H6, "ep": M15},
                {"src": STREAMING},
                [InvalidTarget(node_id="a", declared=H6, source_floor=STREAMING, consumer_ceiling=M15)],
            ),
            # a source slowing down (6h import) pushes the floor above an existing 15min target
            (
                "target_below_drifted_source_floor",
                [("src", "a")],
                {"a": M15},
                {"src": H6},
                [InvalidTarget(node_id="a", declared=M15, source_floor=H6, consumer_ceiling=None)],
            ),
            # everything within bounds -> nothing flagged
            (
                "all_valid",
                [("src", "a"), ("a", "ep")],
                {"a": M15, "ep": M15},
                {"src": STREAMING},
                [],
            ),
        ]
    )
    def test_find_invalid_targets(self, _name, edges, targets, source_intervals, expected):
        self.assertEqual(
            find_invalid_targets(edges=edges, declared_targets=targets, source_intervals=source_intervals), expected
        )


class TestClampToSourceFloor(TestCase):
    @parameterized.expand(
        [
            # finer than the 6h floor -> coarsened to the floor bucket
            ("finer_than_floor", {"a": M15}, {"src": H6}, {"a": H6}, H6),
            # floor is not a bucket (45min) -> clamp up to the nearest bucket (1h), never finer
            ("non_bucket_floor_rounds_up", {"a": M15}, {"src": M45}, {"a": H1}, H1),
            # already at the floor -> untouched
            ("at_floor", {"a": H6}, {"src": H6}, {"a": H6}, None),
            # coarser than the floor -> untouched
            ("coarser_than_floor", {"a": DAY}, {"src": H6}, {"a": DAY}, None),
            # streamed source imposes no floor -> never clamped
            ("streamed_source", {"a": M15}, {"src": STREAMING}, {"a": M15}, None),
            # unscheduled stays unscheduled
            ("unscheduled_untouched", {"a": None}, {"src": H6}, {"a": None}, None),
        ]
    )
    def test_clamp(self, _name, effective, source_intervals, expected_cadences, expected_clamped_to):
        clamped, changes = clamp_to_source_floor(effective, edges=[("src", "a")], source_intervals=source_intervals)
        self.assertEqual(clamped, expected_cadences)
        if expected_clamped_to is None:
            self.assertEqual(changes, [])
        else:
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].node_id, "a")
            self.assertEqual(changes[0].demanded, effective["a"])
            self.assertEqual(changes[0].source_floor, source_intervals["src"])
            self.assertEqual(changes[0].clamped_to, expected_clamped_to)


class TestNormalizeSeedTarget(TestCase):
    @parameterized.expand(
        [
            # already a schedulable bucket within bounds -> unchanged
            ("bucket_within_bounds", M15, STREAMING, M15),
            # non-bucket seed snaps down to the nearest finer bucket (fresher is safe)
            ("non_bucket_snaps_down", M45, STREAMING, M30),
            # a bucket finer than the source floor coarsens up to the floor
            ("finer_than_floor_coarsens", M15, H1, H1),
            # non-bucket over a slow source: snap down then coarsen to the floor
            ("snaps_then_coarsens_to_floor", M45, H6, H6),
            # already coarser than the floor -> left alone
            ("coarser_than_floor_stays", DAY, H6, DAY),
        ]
    )
    def test_normalize(self, _name, seed, source_floor, expected):
        self.assertEqual(normalize_seed_target(seed, source_floor), expected)


class TestBatchBounds(TestCase):
    @parameterized.expand(
        [
            # chain src->a->b: the 6h source floors every descendant
            ("chain_floors_descendants", [("src", "a"), ("a", "b")], {"src": H6}, "b", H6),
            # fan-in of two sources: the node inherits the slowest (daily)
            ("fan_in_takes_slowest_source", [("srcA", "m"), ("srcB", "m")], {"srcA": H6, "srcB": DAY}, "m", DAY),
            # no ancestor source -> no floor
            ("no_source_is_streaming", [("a", "b")], {}, "b", STREAMING),
        ]
    )
    def test_source_floors(self, _name, edges, source_intervals, node_id, expected):
        self.assertEqual(all_source_floors(edges, source_intervals).get(node_id, STREAMING), expected)

    @parameterized.expand(
        [
            # a takes the tightest of its two consumers
            ("tightest_consumer", [("a", "epA"), ("a", "epB")], {"epA": H1, "epB": M15}, "a", M15),
            # transitive: demand propagates up past an untargeted intermediate
            ("transitive_demand", [("a", "b"), ("b", "c")], {"c": H1}, "a", H1),
            # no descendant declares a target -> no ceiling
            ("no_descendant_target", [("a", "b")], {}, "a", None),
        ]
    )
    def test_consumer_ceilings(self, _name, edges, declared_targets, node_id, expected):
        self.assertEqual(all_consumer_ceilings(edges, declared_targets).get(node_id), expected)
