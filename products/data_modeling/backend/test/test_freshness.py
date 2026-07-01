from datetime import timedelta

from unittest import TestCase

from parameterized import parameterized

from products.data_modeling.backend.logic.freshness import (
    STREAMING,
    UnsatisfiableFrequencyError,
    compute_effective_cadences,
    frequency_target_bounds,
    validate_frequency_target,
)

M5 = timedelta(minutes=5)
M15 = timedelta(minutes=15)
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
        self.assertEqual(compute_effective_cadences(nodes=nodes, edges=edges, targets=targets), expected)


class TestFrequencyTargetBounds(TestCase):
    @parameterized.expand(
        [
            # streamed source (events) imposes no floor -> a 15min endpoint is allowed
            (
                "streamed_source_no_floor",
                "ep",
                [("src", "ep")],
                {"ep": M15},
                {"src": STREAMING},
                (STREAMING, None),
            ),
            # imported source refreshing every 6h floors an intermediate node at 6h
            (
                "imported_source_floors",
                "a",
                [("src", "a"), ("a", "ep")],
                {"ep": H1},
                {"src": H6},
                (H6, H1),
            ),
            # ceiling comes from the tightest descendant demand
            (
                "ceiling_from_tightest_descendant",
                "a",
                [("src", "a"), ("a", "epA"), ("a", "epB")],
                {"epA": H1, "epB": M15},
                {"src": STREAMING},
                (STREAMING, M15),
            ),
            # floor above ceiling: no legal target exists (unsatisfiable)
            (
                "unsatisfiable_floor_above_ceiling",
                "a",
                [("src", "a"), ("a", "ep")],
                {"ep": M15},
                {"src": H6},
                (H6, M15),
            ),
        ]
    )
    def test_bounds(self, _name, node_id, edges, targets, source_intervals, expected):
        self.assertEqual(
            frequency_target_bounds(node_id=node_id, edges=edges, targets=targets, source_intervals=source_intervals),
            expected,
        )


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
        ]
    )
    def test_validate(self, _name, node_id, target, edges, targets, source_intervals, ok):
        if ok:
            self.assertIsNone(
                validate_frequency_target(
                    node_id=node_id, target=target, edges=edges, targets=targets, source_intervals=source_intervals
                )
            )
        else:
            with self.assertRaises(UnsatisfiableFrequencyError):
                validate_frequency_target(
                    node_id=node_id, target=target, edges=edges, targets=targets, source_intervals=source_intervals
                )

    def test_unsatisfiable_node_rejects_both_ends(self):
        edges = [("src", "a"), ("a", "ep")]
        targets = {"ep": M15}
        source_intervals = {"src": H6}
        # floor 6h > ceiling 15min: the floor value is too stale for the consumer and the
        # ceiling value is too fresh for the source, so no target is accepted.
        with self.assertRaises(UnsatisfiableFrequencyError):
            validate_frequency_target(
                node_id="a", target=H6, edges=edges, targets=targets, source_intervals=source_intervals
            )
        with self.assertRaises(UnsatisfiableFrequencyError):
            validate_frequency_target(
                node_id="a", target=M15, edges=edges, targets=targets, source_intervals=source_intervals
            )
