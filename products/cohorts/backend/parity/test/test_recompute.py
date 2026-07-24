from datetime import UTC, date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.parity.recompute import (
    _OP_EVAL,
    DayMatch,
    OracleLeaf,
    RecomputeSpec,
    RecomputeUnsupported,
    RunContext,
    _member,
    _TreeGroup,
    _TreeLeaf,
    classify_recompute,
    compute_oracle_members,
    evaluate_tree,
    screen_for_recompute,
)

PACIFIC = ZoneInfo("US/Pacific")
AT = datetime(2026, 7, 24, 18, 0, tzinfo=UTC)  # 2026-07-24 11:00 in US/Pacific
HASH = "aaaaaaaaaaaaaaaa"
HASH2 = "bbbbbbbbbbbbbbbb"


def _behavioral(
    condition_hash: str = HASH,
    value: str = "performed_event",
    key: Any = "$pageview",
    time_value: Any = 7,
    time_interval: Any = "day",
    operator: Optional[str] = None,
    operator_value: Any = None,
    explicit_datetime: Optional[str] = None,
    explicit_datetime_to: Optional[str] = None,
    event_type: str = "events",
    event_filters: Any = None,
    negation: bool = False,
) -> dict:
    node: dict = {
        "type": "behavioral",
        "value": value,
        "key": key,
        "conditionHash": condition_hash,
        "bytecode": ["_H", 1],
        "time_value": time_value,
        "time_interval": time_interval,
        "event_type": event_type,
    }
    if operator is not None:
        node["operator"] = operator
    if operator_value is not None:
        node["operator_value"] = operator_value
    if explicit_datetime is not None:
        node["explicit_datetime"] = explicit_datetime
    if explicit_datetime_to is not None:
        node["explicit_datetime_to"] = explicit_datetime_to
    if event_filters is not None:
        node["event_filters"] = event_filters
    if negation:
        node["negation"] = True
    return node


def _pinned(node: dict) -> dict:
    """Mirror of pin_conditions_for_cohorts leaf resolution (event-name / action)."""
    key = node.get("key")
    is_action = node.get("event_type") == "actions" or isinstance(key, int)
    event_name = key if isinstance(key, str) and not is_action else None
    return {
        "condition_hash": node.get("conditionHash"),
        "value": node.get("value"),
        "time_value": node.get("time_value"),
        "time_interval": node.get("time_interval"),
        "explicit_datetime": node.get("explicit_datetime"),
        "explicit_datetime_to": node.get("explicit_datetime_to"),
        "operator": node.get("operator"),
        "operator_value": node.get("operator_value"),
        "event_name": event_name,
        "is_action": is_action,
    }


def _filters(*leaves: dict, op: str = "AND") -> dict:
    return {"properties": {"type": op, "values": list(leaves)}}


def _screen(*leaves: dict, op: str = "AND"):
    return screen_for_recompute(1, _filters(*leaves, op=op), [_pinned(leaf) for leaf in leaves])


class TestSupportScreen(SimpleTestCase):
    def test_canary_single_performed_event_is_supported(self) -> None:
        result = _screen(_behavioral())
        assert isinstance(result, RecomputeSpec)
        self.assertTrue(result.single_leaf)
        leaf = result.sole_leaf
        self.assertEqual((leaf.event_name, leaf.op, leaf.op_value, leaf.window_days), ("$pageview", "gte", 1, 7))

    @parameterized.expand(
        [
            (
                "event_property_filters",
                _behavioral(event_filters=[{"key": "x", "value": "y"}]),
                "has_event_property_filters",
            ),
            ("action_by_event_type", _behavioral(event_type="actions"), "action_leaf"),
            ("action_by_int_key", _behavioral(key=42), "action_leaf"),
            ("sub_day_hour_window", _behavioral(time_interval="hour", time_value=5), "sub_day_window"),
            ("sequence_value", _behavioral(value="performed_event_sequence"), "sequence_or_lifecycle_value"),
            (
                "absolute_explicit_range",
                _behavioral(explicit_datetime="2026-01-01", explicit_datetime_to="2026-02-01"),
                "absolute_explicit_range",
            ),
            (
                "two_sided_relative_range",
                _behavioral(explicit_datetime="-30d", explicit_datetime_to="-7d"),
                "relative_range_unsupported",
            ),
            (
                "unparseable_explicit_bound",
                _behavioral(explicit_datetime="not-a-date"),
                "unparseable_explicit_bound",
            ),
            ("multiple_zero_day_window", _behavioral(value="performed_event_multiple", time_value=0), "sub_day_window"),
        ]
    )
    def test_unsupported_leaf_reasons(self, _name: str, leaf: dict, reason: str) -> None:
        result = _screen(leaf)
        self.assertEqual(result, RecomputeUnsupported(reason))

    @parameterized.expand(
        [
            (
                "person_leaf",
                {"type": "person", "key": "email", "value": "a@b.com", "conditionHash": HASH},
                "person_property_leaf",
            ),
            ("cohort_ref", {"type": "cohort", "key": "id", "value": 7}, "cohort_ref_leaf"),
        ]
    )
    def test_non_behavioral_leaves_are_unsupported(self, _name: str, leaf: dict, reason: str) -> None:
        # Person/cohort-ref leaves have no pinned behavioral condition; the raw tree walk still classifies them.
        result = screen_for_recompute(1, _filters(leaf), [])
        self.assertEqual(result, RecomputeUnsupported(reason))

    def test_relative_lower_only_explicit_equals_time_value_interval(self) -> None:
        # "-7d" and time_value:7/day must resolve to the same window — the same oracle query.
        explicit = _screen(_behavioral(time_value=None, time_interval=None, explicit_datetime="-7d"))
        interval = _screen(_behavioral(time_value=7, time_interval="day"))
        assert isinstance(explicit, RecomputeSpec) and isinstance(interval, RecomputeSpec)
        self.assertEqual(explicit.sole_leaf.window_days, 7)
        self.assertEqual(explicit.sole_leaf.window_days, interval.sole_leaf.window_days)

    def test_multiple_operator_defaults_to_eq_and_clamps_negative_value(self) -> None:
        # performed_event_multiple with no operator -> eq; a negative operator_value clamps to 0.
        result = _screen(_behavioral(value="performed_event_multiple", operator=None, operator_value=-5))
        assert isinstance(result, RecomputeSpec)
        self.assertEqual((result.sole_leaf.op, result.sole_leaf.op_value), ("eq", 0))

    def test_multiple_maps_gte_operator_and_value(self) -> None:
        result = _screen(_behavioral(value="performed_event_multiple", operator="gte", operator_value=3))
        assert isinstance(result, RecomputeSpec)
        self.assertEqual((result.sole_leaf.op, result.sole_leaf.op_value), ("gte", 3))

    def test_duplicate_condition_hash_dedupes_to_one_leaf(self) -> None:
        leaf = _behavioral()
        result = screen_for_recompute(1, _filters(leaf, leaf), [_pinned(leaf)])
        assert isinstance(result, RecomputeSpec)
        self.assertEqual(len(result.leaves), 1)
        self.assertTrue(result.single_leaf)


class TestMembershipFloor(SimpleTestCase):
    @parameterized.expand(
        [
            # count 0 is never a member, even under lte/lt/eq 0 (the count >= 1 floor).
            ("lte5_over0", 0, "lte", 5, False),
            ("lt5_over0", 0, "lt", 5, False),
            ("eq0_over0", 0, "eq", 0, False),
            ("gte1_over0", 0, "gte", 1, False),
            # count 1 satisfies lte/eq 1 but never eq 0.
            ("lte5_over1", 1, "lte", 5, True),
            ("eq1_over1", 1, "eq", 1, True),
            ("eq0_over1", 1, "eq", 0, False),
        ]
    )
    def test_member_floor(self, _name: str, count: int, op: str, op_value: int, expected: bool) -> None:
        self.assertEqual(_member(count, op, op_value), expected)


class TestTreeEvaluation(SimpleTestCase):
    def test_and_neg_b_truth_table(self) -> None:
        tree = _TreeGroup(op="AND", children=(_TreeLeaf(HASH, False), _TreeLeaf(HASH2, True)))
        cases = [((True, True), False), ((True, False), True), ((False, True), False), ((False, False), False)]
        for (a, b), expected in cases:
            self.assertEqual(evaluate_tree(tree, {HASH: a, HASH2: b}), expected, f"A={a} ¬B={b}")

    def test_absent_leaf_reads_false_then_negation(self) -> None:
        # A positive leaf absent from the bit map reads false; a negated absent leaf reads true.
        self.assertFalse(evaluate_tree(_TreeLeaf(HASH, False), {}))
        self.assertTrue(evaluate_tree(_TreeLeaf(HASH, True), {}))

    def test_empty_group_identities(self) -> None:
        self.assertTrue(evaluate_tree(_TreeGroup(op="AND", children=()), {}))
        self.assertFalse(evaluate_tree(_TreeGroup(op="OR", children=()), {}))

    def test_compute_oracle_members_and_minus_b(self) -> None:
        spec = RecomputeSpec(
            cohort_id=1,
            root=_TreeGroup(op="AND", children=(_TreeLeaf(HASH, False), _TreeLeaf(HASH2, True))),
            leaves={
                HASH: OracleLeaf(HASH, "$pageview", "gte", 1, 7),
                HASH2: OracleLeaf(HASH2, "purchase", "gte", 1, 7),
            },
            single_leaf=False,
        )
        # A minus B: {a1, a2} minus {a2, b1} = {a1}. b1 (only in B) composes to false and is excluded.
        members = compute_oracle_members(spec, {HASH: {"a1", "a2"}, HASH2: {"a2", "b1"}})
        self.assertEqual(members, {"a1"})

    def test_compute_oracle_members_single_leaf_is_the_set(self) -> None:
        spec = RecomputeSpec(
            cohort_id=1,
            root=_TreeLeaf(HASH, False),
            leaves={HASH: OracleLeaf(HASH, "$pageview", "gte", 1, 7)},
            single_leaf=True,
        )
        self.assertEqual(compute_oracle_members(spec, {HASH: {"a", "b"}}), {"a", "b"})


def _spec(op: str = "gte", op_value: int = 1, window_days: int = 7, single_leaf: bool = True) -> RecomputeSpec:
    leaves = {HASH: OracleLeaf(HASH, "$pageview", op, op_value, window_days)}
    if not single_leaf:
        leaves[HASH2] = OracleLeaf(HASH2, "purchase", op, op_value, window_days)
    return RecomputeSpec(cohort_id=1, root=_TreeLeaf(HASH, False), leaves=leaves, single_leaf=single_leaf)


def _ctx(**overrides: Any) -> RunContext:
    defaults: dict[str, Any] = {
        "run_id": "run-1",
        "status": "seeding",
        "boundary_at": datetime(2026, 7, 20, 19, 0, tzinfo=UTC),  # 2026-07-20 12:00 in US/Pacific
        "run_timezone": "US/Pacific",
        "boundary_day": date(2026, 7, 20),
        "confirmed_days": frozenset({date(2026, 7, 17), date(2026, 7, 18)}),
        "non_confirmed_chunks": 0,
        "shape_hash_drift": False,
    }
    defaults.update(overrides)
    return RunContext(**defaults)


def _dm(day: date, bucket: str, matches: int = 1) -> DayMatch:
    return DayMatch(day=day, bucket=bucket, matches=matches)


class TestMissingSegmentation(SimpleTestCase):
    @parameterized.expand(
        [
            # 2026-07-24 is at_day; grace bucket there depends only on last grace-minutes.
            ("grace", [_dm(date(2026, 7, 24), "grace")], "missing_grace"),
            # 2026-07-18 is a confirmed seed day -> should have been seeded (gates FAIL).
            ("seed_domain", [_dm(date(2026, 7, 18), "pre_boundary")], "missing_seed_domain"),
            # 2026-07-20 is the boundary day, pre-boundary -> the decaying gap.
            ("boundary_day", [_dm(date(2026, 7, 20), "pre_boundary")], "missing_boundary_day"),
            # 2026-07-19 is a pre-boundary window day with no confirmed chunk (gates FAIL).
            ("unseeded_day", [_dm(date(2026, 7, 19), "pre_boundary")], "missing_unseeded_day"),
            # 2026-07-21 is post-boundary -> live-path timing.
            ("post_boundary", [_dm(date(2026, 7, 21), "post_boundary")], "missing_post_boundary"),
        ]
    )
    def test_missing_person_precedence(self, name: str, matches: list[DayMatch], expected_field: str) -> None:
        person = "p"
        row = classify_recompute(
            spec=_spec(),
            name="c",
            fold_members=set(),
            oracle_members={person},
            day_counts={person: matches},
            ctx=_ctx(),
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(getattr(row, expected_field), 1, name)
        self.assertEqual(row.missing, 1)

    def test_seed_domain_precedence_over_boundary(self) -> None:
        # A person qualifying via both a confirmed seed day and the boundary day is a seed-domain miss:
        # the seeder already covered them, so it gates FAIL rather than being written off as the gap.
        row = classify_recompute(
            spec=_spec(),
            name="c",
            fold_members=set(),
            oracle_members={"p"},
            day_counts={"p": [_dm(date(2026, 7, 18), "pre_boundary"), _dm(date(2026, 7, 20), "pre_boundary")]},
            ctx=_ctx(),
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(row.missing_seed_domain, 1)
        self.assertEqual(row.verdict, "FAIL")

    def test_verdict_fail_on_seed_or_unseeded_pass_on_boundary(self) -> None:
        pass_row = classify_recompute(
            spec=_spec(),
            name="c",
            fold_members=set(),
            oracle_members={"b"},
            day_counts={"b": [_dm(date(2026, 7, 20), "pre_boundary")]},
            ctx=_ctx(),
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(pass_row.verdict, "PASS")
        self.assertEqual(pass_row.missing_boundary_day, 1)


class TestEvictionAndUnsegmented(SimpleTestCase):
    def test_eviction_pending_splits_false_members(self) -> None:
        # extra_day = at_day - N - 1 = 2026-07-16. A false member with a match there is still a member
        # under the just-slid-out window (sweep lag), not over-inclusion.
        row = classify_recompute(
            spec=_spec(),
            name="c",
            fold_members={"evict", "hard"},
            oracle_members=set(),
            day_counts={"evict": [_dm(date(2026, 7, 16), "pre_boundary")], "hard": []},
            ctx=_ctx(),
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(row.false_members, 2)
        self.assertEqual(row.eviction_pending, 1)
        self.assertEqual(row.false_hard, 1)
        self.assertEqual(row.verdict, "FAIL")  # the one hard over-count gates FAIL

    def test_non_monotone_op_leaves_missing_unsegmented(self) -> None:
        row = classify_recompute(
            spec=_spec(op="lte", op_value=2),
            name="c",
            fold_members=set(),
            oracle_members={"p"},
            day_counts={"p": [_dm(date(2026, 7, 18), "pre_boundary")]},
            ctx=_ctx(),
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(row.missing_unsegmented, 1)
        self.assertEqual(row.missing_seed_domain, 0)
        self.assertEqual(row.verdict, "PASS")  # membership parity only; no domain gate
        self.assertTrue(any("non-monotone" in note for note in row.notes))

    def test_multi_leaf_leaves_missing_unsegmented_and_false_hard(self) -> None:
        row = classify_recompute(
            spec=_spec(single_leaf=False),
            name="c",
            fold_members={"x"},
            oracle_members={"p"},
            day_counts={},
            ctx=_ctx(),
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(row.missing_unsegmented, 1)
        self.assertEqual(row.false_hard, 1)
        self.assertEqual(row.eviction_pending, 0)
        self.assertTrue(any("multi-leaf" in note for note in row.notes))

    def test_no_run_context_leaves_missing_unsegmented(self) -> None:
        row = classify_recompute(
            spec=_spec(),
            name="c",
            fold_members=set(),
            oracle_members={"p"},
            day_counts={"p": [_dm(date(2026, 7, 18), "pre_boundary")]},
            ctx=None,
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(row.missing_unsegmented, 1)
        self.assertIsNone(row.run_id)
        self.assertTrue(any("no backfill run" in note for note in row.notes))


class TestExpiryCurve(SimpleTestCase):
    def test_boundary_class_expiry_is_newest_match_plus_window_plus_one(self) -> None:
        # A boundary-day (2026-07-20) match with N=7 ages out at 2026-07-20 + 7 + 1 = 2026-07-28.
        row = classify_recompute(
            spec=_spec(window_days=7),
            name="c",
            fold_members=set(),
            oracle_members={"p"},
            day_counts={"p": [_dm(date(2026, 7, 20), "pre_boundary")]},
            ctx=_ctx(),
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(row.expires_by_day, {"2026-07-28": 1})

    def test_expiry_counts_group_by_date(self) -> None:
        row = classify_recompute(
            spec=_spec(window_days=7),
            name="c",
            fold_members=set(),
            oracle_members={"p1", "p2"},
            day_counts={
                "p1": [_dm(date(2026, 7, 20), "pre_boundary")],
                "p2": [_dm(date(2026, 7, 20), "pre_boundary")],
            },
            ctx=_ctx(),
            at=AT,
            seg_tz=PACIFIC,
        )
        self.assertEqual(row.expires_by_day, {"2026-07-28": 2})


class TestOpWhitelistParity(SimpleTestCase):
    def test_eval_and_sql_whitelists_agree(self) -> None:
        # A drift where an op gains a Python comparator but no SQL rendering (or vice versa) would let a
        # supported leaf reach a KeyError at query time; keep the two op tables in lockstep.
        from products.cohorts.backend.parity.oracle import _MEMBER_SET_SQL, _OP_SQL

        self.assertEqual(set(_OP_EVAL), set(_OP_SQL))
        for comparator in _OP_SQL.values():
            rendered = _MEMBER_SET_SQL.format(overrides_join="", op=comparator)
            self.assertIn(f"match_count {comparator} %(op_value)s", rendered)
            self.assertNotIn("{op}", rendered)
