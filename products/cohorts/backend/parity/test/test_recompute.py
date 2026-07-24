from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.models.leaf_shape import BehavioralLeafKey
from products.cohorts.backend.parity.fold import MembershipRecord
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
GRACE = timedelta(minutes=10)
HASH = "aaaaaaaaaaaaaaaa"
HASH2 = "bbbbbbbbbbbbbbbb"


def _key(condition_hash: str = HASH, **overrides: Any) -> BehavioralLeafKey:
    fields: dict[str, Any] = {
        "condition_hash": condition_hash,
        "value": "performed_event",
        "time_value": 7,
        "time_interval": "day",
        "explicit_datetime": "",
        "explicit_datetime_to": "",
        "operator": "",
        "operator_value": 0,
    }
    fields.update(overrides)
    return BehavioralLeafKey(**fields)


KEY = _key()
KEY2 = _key(HASH2)


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


def _screen(*leaves: dict, op: str = "AND", max_window_days: int = 400):
    return screen_for_recompute(
        1, _filters(*leaves, op=op), [_pinned(leaf) for leaf in leaves], max_window_days=max_window_days
    )


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
            ("missing_interval", _behavioral(time_interval=None), "missing_window"),
            # select.rs maps every zero-effective-window `performed_event_multiple` to HourlyDeferred,
            # whether the window is sub-day or an explicit shape it cannot slide.
            (
                "multiple_zero_day_window",
                _behavioral(value="performed_event_multiple", time_value=0),
                "hourly_deferred",
            ),
            (
                "multiple_absolute_explicit_range",
                _behavioral(
                    value="performed_event_multiple", explicit_datetime="2026-01-01", explicit_datetime_to="2026-02-01"
                ),
                "hourly_deferred",
            ),
            ("window_over_cap", _behavioral(time_value=10, time_interval="year"), "window_exceeds_max_days"),
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
        result = screen_for_recompute(1, _filters(leaf), [], max_window_days=400)
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

    def test_identical_leaves_dedupe_to_one_leaf(self) -> None:
        leaf = _behavioral()
        result = screen_for_recompute(1, _filters(leaf, leaf), [_pinned(leaf)], max_window_days=400)
        assert isinstance(result, RecomputeSpec)
        self.assertEqual(len(result.leaves), 1)
        self.assertTrue(result.single_leaf)

    def test_same_condition_hash_different_window_stays_two_leaves(self) -> None:
        # conditionHash digests only the event matcher, so "did $pageview in 30d AND NOT did $pageview
        # in 1d" — a routine churn shape — shares one hash across two leaves. Collapsing them would
        # evaluate `bit AND NOT bit`, i.e. an empty oracle set and a FAIL on every fold member.
        wide = _behavioral(time_value=30)
        narrow = _behavioral(time_value=1, negation=True)
        result = screen_for_recompute(1, _filters(wide, narrow), [_pinned(wide), _pinned(narrow)], max_window_days=400)
        assert isinstance(result, RecomputeSpec)
        self.assertEqual(sorted(leaf.window_days for leaf in result.leaves.values()), [1, 30])
        self.assertFalse(result.single_leaf)
        members = compute_oracle_members(
            result,
            {_key(time_value=30): {"stale", "active"}, _key(time_value=1): {"active"}},
        )
        self.assertEqual(members, {"stale"})


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
        tree = _TreeGroup(op="AND", children=(_TreeLeaf(KEY, False), _TreeLeaf(KEY2, True)))
        cases = [((True, True), False), ((True, False), True), ((False, True), False), ((False, False), False)]
        for (a, b), expected in cases:
            self.assertEqual(evaluate_tree(tree, {KEY: a, KEY2: b}), expected, f"A={a} ¬B={b}")

    def test_absent_leaf_reads_false_then_negation(self) -> None:
        # A positive leaf absent from the bit map reads false; a negated absent leaf reads true.
        self.assertFalse(evaluate_tree(_TreeLeaf(KEY, False), {}))
        self.assertTrue(evaluate_tree(_TreeLeaf(KEY, True), {}))

    def test_empty_group_identities(self) -> None:
        self.assertTrue(evaluate_tree(_TreeGroup(op="AND", children=()), {}))
        self.assertFalse(evaluate_tree(_TreeGroup(op="OR", children=()), {}))

    def test_compute_oracle_members_and_minus_b(self) -> None:
        spec = RecomputeSpec(
            cohort_id=1,
            root=_TreeGroup(op="AND", children=(_TreeLeaf(KEY, False), _TreeLeaf(KEY2, True))),
            leaves={
                KEY: OracleLeaf(KEY, "$pageview", "gte", 1, 7),
                KEY2: OracleLeaf(KEY2, "purchase", "gte", 1, 7),
            },
            single_leaf=False,
        )
        # A minus B: {a1, a2} minus {a2, b1} = {a1}. b1 (only in B) composes to false and is excluded.
        members = compute_oracle_members(spec, {KEY: {"a1", "a2"}, KEY2: {"a2", "b1"}})
        self.assertEqual(members, {"a1"})

    def test_compute_oracle_members_single_leaf_is_the_set(self) -> None:
        spec = RecomputeSpec(
            cohort_id=1,
            root=_TreeLeaf(KEY, False),
            leaves={KEY: OracleLeaf(KEY, "$pageview", "gte", 1, 7)},
            single_leaf=True,
        )
        self.assertEqual(compute_oracle_members(spec, {KEY: {"a", "b"}}), {"a", "b"})


def _spec(op: str = "gte", op_value: int = 1, window_days: int = 7, single_leaf: bool = True) -> RecomputeSpec:
    leaves = {KEY: OracleLeaf(KEY, "$pageview", op, op_value, window_days)}
    if not single_leaf:
        leaves[KEY2] = OracleLeaf(KEY2, "purchase", op, op_value, window_days)
    return RecomputeSpec(cohort_id=1, root=_TreeLeaf(KEY, False), leaves=leaves, single_leaf=single_leaf)


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


def _fold(*person_ids: str, entered_at: datetime = datetime(2026, 7, 1, tzinfo=UTC)) -> dict[str, MembershipRecord]:
    return {pid: MembershipRecord(status="entered", last_updated=entered_at) for pid in person_ids}


def _classify(**overrides: Any):
    defaults: dict[str, Any] = {
        "spec": _spec(),
        "name": "c",
        "fold_records": {},
        "oracle_members": set(),
        "day_counts": {},
        "extended_leaf_counts": {},
        "ctx": _ctx(),
        "at": AT,
        "grace": GRACE,
        "team_tz": PACIFIC,
    }
    defaults.update(overrides)
    return classify_recompute(**defaults)


class TestMissingSegmentation(SimpleTestCase):
    @parameterized.expand(
        [
            # 2026-07-24 is at_day; grace bucket there depends only on last grace-minutes.
            ("grace", [_dm(date(2026, 7, 24), "grace")], "missing_grace", "PASS"),
            # 2026-07-18 is a confirmed seed day -> should have been seeded (gates FAIL).
            ("seed_domain", [_dm(date(2026, 7, 18), "pre_boundary")], "missing_seed_domain", "FAIL"),
            # 2026-07-20 is the boundary day, pre-boundary -> the decaying gap.
            ("boundary_day", [_dm(date(2026, 7, 20), "pre_boundary")], "missing_boundary_day", "PASS"),
            # 2026-07-19 is a pre-boundary window day with no confirmed chunk (gates FAIL).
            ("unseeded_day", [_dm(date(2026, 7, 19), "pre_boundary")], "missing_unseeded_day", "FAIL"),
            # 2026-07-21 is post-boundary: only the live path could have entered them, so a drop there
            # is exactly what this gate exists to catch — grace is the lever for known live lag.
            ("post_boundary", [_dm(date(2026, 7, 21), "post_boundary")], "missing_post_boundary", "FAIL"),
        ]
    )
    def test_missing_person_precedence(
        self, name: str, matches: list[DayMatch], expected_field: str, verdict: str
    ) -> None:
        row = _classify(oracle_members={"p"}, day_counts={"p": matches})
        self.assertEqual(getattr(row, expected_field), 1, name)
        self.assertEqual(row.missing, 1)
        self.assertEqual(row.verdict, verdict, name)
        self.assertEqual(row.samples[expected_field], ("p",))

    def test_seed_domain_precedence_over_boundary(self) -> None:
        # A person qualifying via both a confirmed seed day and the boundary day is a seed-domain miss:
        # the seeder already covered them, so it gates FAIL rather than being written off as the gap.
        row = _classify(
            oracle_members={"p"},
            day_counts={"p": [_dm(date(2026, 7, 18), "pre_boundary"), _dm(date(2026, 7, 20), "pre_boundary")]},
        )
        self.assertEqual(row.missing_seed_domain, 1)
        self.assertEqual(row.verdict, "FAIL")


class TestEvictionAndUnsegmented(SimpleTestCase):
    def test_eviction_pending_splits_false_members(self) -> None:
        # "evict" still satisfies the predicate once the window slides back a day (the tz-midnight
        # sweep has not caught up); "hard" does not, so it is real over-inclusion.
        row = _classify(
            fold_records=_fold("evict", "hard"),
            extended_leaf_counts={KEY: {"evict": 1, "hard": 0}},
        )
        self.assertEqual(row.false_members, 2)
        self.assertEqual(row.eviction_pending, 1)
        self.assertEqual(row.false_hard, 1)
        self.assertEqual(row.verdict, "FAIL")  # the one hard over-count gates FAIL
        self.assertEqual(row.samples["false_hard"], ("hard",))

    def test_just_entered_false_member_is_sweep_lag_not_over_inclusion(self) -> None:
        # A late-ingested historical event enters the person now and only a sweep tick can clear them,
        # so a fold record younger than the grace window is lag, however old the matching event is.
        row = _classify(fold_records=_fold("fresh", entered_at=AT - timedelta(minutes=1)))
        self.assertEqual((row.eviction_pending, row.false_hard), (1, 0))
        self.assertEqual(row.verdict, "PASS")

    def test_multi_leaf_over_count_uses_the_tree_for_the_eviction_split(self) -> None:
        # Every leaf slides back a day and the tree is re-evaluated, so a multi-leaf cohort near
        # team-tz midnight is not gated on sweep lag the way a single-leaf one isn't.
        spec = RecomputeSpec(
            cohort_id=1,
            root=_TreeGroup(op="AND", children=(_TreeLeaf(KEY, False), _TreeLeaf(KEY2, False))),
            leaves={KEY: OracleLeaf(KEY, "$pageview", "gte", 1, 7), KEY2: OracleLeaf(KEY2, "purchase", "gte", 1, 7)},
            single_leaf=False,
        )
        row = _classify(
            spec=spec,
            fold_records=_fold("both", "one"),
            extended_leaf_counts={KEY: {"both": 1, "one": 1}, KEY2: {"both": 1, "one": 0}},
        )
        self.assertEqual((row.eviction_pending, row.false_hard), (1, 1))
        self.assertEqual(row.samples["false_hard"], ("one",))

    @parameterized.expand(
        [
            ("non_monotone_op", {"spec": _spec(op="lte", op_value=2)}, "non-monotone"),
            ("multi_leaf", {"spec": _spec(single_leaf=False)}, "multi-leaf"),
            ("no_run_context", {"ctx": None}, "no backfill run"),
        ]
    )
    def test_unadjudicated_missing_is_skip_not_pass(self, _name: str, overrides: dict, note: str) -> None:
        # Reporting PASS here would certify a parity the command never established.
        row = _classify(oracle_members={"p"}, day_counts={"p": [_dm(date(2026, 7, 18), "pre_boundary")]}, **overrides)
        self.assertEqual(row.missing_unsegmented, 1)
        self.assertEqual(row.missing_seed_domain, 0)
        self.assertEqual(row.verdict, "SKIP")
        self.assertTrue(any(note in n for n in row.notes), row.notes)

    def test_caller_supplied_unsegmentable_reason_wins(self) -> None:
        row = _classify(
            oracle_members={"p"},
            segmentable=False,
            extra_notes=["exceeds the per-person read cap"],
        )
        self.assertEqual(row.missing_unsegmented, 1)
        self.assertEqual(row.notes[0], "exceeds the per-person read cap")

    def test_hard_over_count_outranks_unadjudicated_missing(self) -> None:
        row = _classify(spec=_spec(single_leaf=False), fold_records=_fold("x"), oracle_members={"p"})
        self.assertEqual(row.verdict, "FAIL")


class TestExpiryCurve(SimpleTestCase):
    def test_expiry_is_driven_by_the_oldest_still_needed_match(self) -> None:
        # threshold 2 across a confirmed seed day and the boundary day: dropping the newer match alone
        # still leaves the person short, so the *older* match's age-out date is when they fall out.
        row = _classify(
            spec=_spec(op="gte", op_value=2, window_days=7),
            oracle_members={"p"},
            day_counts={
                "p": [_dm(date(2026, 7, 18), "pre_boundary"), _dm(date(2026, 7, 20), "pre_boundary")],
            },
        )
        self.assertEqual(row.missing_boundary_day, 1)
        self.assertEqual(row.expires_by_day, {"2026-07-26": 1})  # 2026-07-18 + 7 + 1

    def test_expiry_counts_group_by_date(self) -> None:
        row = _classify(
            spec=_spec(window_days=7),
            oracle_members={"p1", "p2"},
            day_counts={
                "p1": [_dm(date(2026, 7, 20), "pre_boundary")],
                "p2": [_dm(date(2026, 7, 20), "pre_boundary")],
            },
        )
        self.assertEqual(row.expires_by_day, {"2026-07-28": 2})  # 2026-07-20 + 7 + 1


class TestOpWhitelistParity(SimpleTestCase):
    def test_eval_and_sql_whitelists_agree(self) -> None:
        # A drift where an op gains a Python comparator but no SQL rendering (or vice versa) would let a
        # supported leaf reach a KeyError at query time; keep the two op tables in lockstep.
        from products.cohorts.backend.parity.oracle import _MEMBER_SET_SQL, _OP_SQL, _render

        self.assertEqual(set(_OP_EVAL), set(_OP_SQL))
        for comparator in _OP_SQL.values():
            rendered = _render(_MEMBER_SET_SQL, op=comparator)
            self.assertIn(f"match_count {comparator} %(op_value)s", rendered)
            self.assertNotIn("{op}", rendered)
