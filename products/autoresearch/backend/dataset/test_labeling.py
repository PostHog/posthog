from datetime import timedelta
from typing import Any

from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.hogql_queries.query_runner import ExecutionMode

from products.autoresearch.backend.dataset.labeling import (
    _build_labeled_users_cte,
    _build_population_conditions,
    _build_population_kind_conditions,
    _substitute_anchors,
    build_eligible_count_sql,
    build_inference_anchors_sql,
    build_inference_features_sql,
    build_random_t0_labeler_sql,
    strip_sql_comments,
)
from products.autoresearch.backend.query import run_hogql_rows


class TestStripSqlComments(BaseTest):
    @parameterized.expand(
        [
            ("line_comment", "SELECT a -- the count\nFROM t", "SELECT a \nFROM t"),
            ("block_comment", "SELECT a /* inline */ FROM t", "SELECT a   FROM t"),
            ("trailing_line_comment", "SELECT a FROM t -- trailing", "SELECT a FROM t "),
            ("no_comment", "SELECT a FROM t", "SELECT a FROM t"),
        ]
    )
    def test_strips_comments(self, _name: str, sql: str, expected: str) -> None:
        self.assertEqual(strip_sql_comments(sql), expected)

    def test_preserves_double_dash_inside_string_literal(self) -> None:
        sql = "SELECT 'a -- b' AS x FROM t"
        self.assertEqual(strip_sql_comments(sql), sql)

    def test_preserves_escaped_quote_inside_string(self) -> None:
        sql = "SELECT 'it''s -- fine' AS x FROM t"
        self.assertEqual(strip_sql_comments(sql), sql)

    def test_preserves_block_comment_markers_inside_string(self) -> None:
        sql = "SELECT '/* not a comment */' AS x FROM t"
        self.assertEqual(strip_sql_comments(sql), sql)

    def test_preserves_double_dash_inside_backtick_identifier(self) -> None:
        sql = "SELECT `weird--name` FROM t"
        self.assertEqual(strip_sql_comments(sql), sql)


class TestSubstituteAnchors(BaseTest):
    def test_placeholder_in_line_comment_does_not_corrupt_substitution(self) -> None:
        # A multi-line anchors subquery substituted into a `--` comment would
        # escape the comment and break the parse — stripping comments first avoids it.
        feature_sql = "SELECT a.person_id AS distinct_id\n-- read FROM {anchors} a here\nFROM {anchors} a"
        anchors = "(SELECT person_id, t0_ts AS cutoff_ts\nFROM labeled_anchors)"
        result = _substitute_anchors(feature_sql, anchors)
        self.assertNotIn("--", result)
        # The real FROM {anchors} got substituted; the commented one was removed.
        self.assertEqual(result.count("labeled_anchors"), 1)

    def test_substitutes_all_real_occurrences(self) -> None:
        feature_sql = "SELECT * FROM {anchors} a JOIN {anchors} b ON a.person_id = b.person_id"
        result = _substitute_anchors(feature_sql, "(SELECT 1)")
        self.assertEqual(result.count("(SELECT 1)"), 2)
        self.assertNotIn("{anchors}", result)


class TestBuildInferenceFeaturesSql(BaseTest):
    def test_comment_in_feature_sql_is_stripped_before_substitution(self) -> None:
        feature_sql = "SELECT a.person_id AS distinct_id -- {anchors}\nFROM {anchors} a"
        sql, _values = build_inference_features_sql(
            feature_sql=feature_sql,
            lookback_days=30,
            inference_population=None,
        )
        self.assertNotIn("{anchors}", sql)
        self.assertNotIn("--", sql)


class TestPopulationFilterCompilation(SimpleTestCase):
    # A filter that cannot be compiled must raise: skipping it would silently widen the
    # population, and inference writes person properties for everyone it scores.

    @parameterized.expand(
        [
            ("cohort_type", [{"key": "id", "type": "cohort", "operator": "exact", "value": 123}]),
            ("unknown_operator", [{"key": "plan", "type": "person", "operator": "regex", "value": "x"}]),
            ("missing_key", [{"type": "person", "operator": "is_set"}]),
        ]
    )
    def test_uncompilable_filter_raises_instead_of_widening(self, _name: str, properties: list[dict[str, Any]]) -> None:
        with self.assertRaises(ValueError):
            _build_population_conditions(properties)

    def test_empty_allowlist_matches_nobody(self) -> None:
        parts, _values = _build_population_conditions(
            [{"key": "plan", "type": "person", "operator": "exact", "value": []}]
        )
        self.assertEqual(parts, ["1 = 0"])

    def test_empty_denylist_excludes_nobody(self) -> None:
        parts, _values = _build_population_conditions(
            [{"key": "plan", "type": "person", "operator": "is_not", "value": []}]
        )
        self.assertEqual(parts, [])


class TestPopulationKindCompilation(SimpleTestCase):
    # Guards against the regression where a semantic population spec ({"kind": ...})
    # fell through the compiler and silently widened to "all identified users".

    @parameterized.expand(
        [
            (
                "performed_any_event",
                {"kind": "performed_event_within_days", "days": 30},
                ["person_id IN (SELECT DISTINCT person_id FROM events"],
                {"popk_days": 30},
            ),
            (
                "performed_specific_event",
                {"kind": "performed_event_within_days", "days": 30, "event": "$pageview"},
                ["person_id IN (SELECT DISTINCT person_id FROM events", "event = {popk_event}"],
                {"popk_days": 30, "popk_event": "$pageview"},
            ),
            (
                "first_seen",
                {"kind": "person_first_seen_within_days", "days": 14},
                ["person.created_at >= now() - toIntervalDay({popk_days})"],
                {"popk_days": 14},
            ),
            (
                "active_not_performed_target",
                {"kind": "active_not_performed_target", "active_within_days": 30},
                ["person_id IN (SELECT DISTINCT person_id FROM events", "person_id NOT IN", "(event = {target})"],
                {"popk_active_days": 30, "target": "feature_used"},
            ),
            (
                "ever_performed_event",
                {"kind": "ever_performed_event", "event": "checkout"},
                ["person_id IN (SELECT DISTINCT person_id FROM events", "event = {popk_event}"],
                {"popk_event": "checkout"},
            ),
            (
                "ever_performed_target",
                {"kind": "ever_performed_target"},
                ["person_id IN (SELECT DISTINCT person_id FROM events", "(event = {target})"],
                {"target": "feature_used"},
            ),
        ]
    )
    def test_inference_anchors_filter_kind_population(
        self,
        _name: str,
        population: dict[str, Any],
        fragments: list[str],
        expected_values: dict[str, Any],
    ) -> None:
        sql, values = build_inference_anchors_sql(
            lookback_days=90, inference_population=population, target_event="feature_used"
        )
        for fragment in fragments:
            self.assertIn(fragment, sql)
        for key, expected in expected_values.items():
            self.assertEqual(values[key], expected)

    def test_eligible_count_filters_kind_population(self) -> None:
        sql, values = build_eligible_count_sql(
            horizon_days=7,
            lookback_days=90,
            training_population={"kind": "performed_event_within_days", "days": 30},
        )
        self.assertIn("person_id IN (SELECT DISTINCT person_id FROM events", sql)
        self.assertEqual(values["popk_days"], 30)

    def test_inference_backfill_anchors_kind_windows_at_cutoff(self) -> None:
        sql, _values = build_inference_anchors_sql(
            lookback_days=90,
            inference_population={"kind": "performed_event_within_days", "days": 30},
            cutoff_ts=1_700_000_000,
        )
        self.assertIn("timestamp >= fromUnixTimestamp({cutoff_ts}) - toIntervalDay({popk_days})", sql)

    @parameterized.expand(
        [
            ("unknown_kind", {"kind": "bogus"}),
            ("missing_days", {"kind": "performed_event_within_days"}),
            ("non_int_days", {"kind": "person_first_seen_within_days", "days": "14"}),
            ("missing_active_days", {"kind": "active_not_performed_target"}),
            ("missing_event", {"kind": "ever_performed_event"}),
        ]
    )
    def test_uncompilable_kind_raises_instead_of_widening(self, _name: str, population: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            build_inference_anchors_sql(lookback_days=90, inference_population=population, target_event="x")

    @parameterized.expand(
        [
            ("adoption", {"kind": "active_not_performed_target", "active_within_days": 30}),
            ("repeat", {"kind": "ever_performed_target"}),
        ]
    )
    def test_target_relative_kind_requires_the_target_predicate(self, _name: str, population: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            _build_population_kind_conditions(population)


class TestPopulationKindTrainingSemantics(SimpleTestCase):
    # Training decides membership per user at T0, never as of now(): deciding it as of
    # now() admits users on activity after T0 (including the outcome window), and a
    # row-level "has not performed the target" filter would delete exactly the users
    # whose post-T0 adoption provides the positive labels.

    _EVENT_TS = "toInt(toUnixTimestamp(e.timestamp))"

    @parameterized.expand(
        [
            (
                "adoption_kind",
                {"kind": "active_not_performed_target", "active_within_days": 30},
                [
                    f"HAVING max(({_EVENT_TS} >= u.t0_ts - {{popk_active_days}} * 86400 AND {_EVENT_TS} < u.t0_ts)) = 1",
                    f"max(({_EVENT_TS} < u.t0_ts AND (event = {{target}}))) = 0",
                ],
                ["NOT IN"],
            ),
            (
                "repeat_target_kind",
                {"kind": "ever_performed_target"},
                [f"HAVING max(({_EVENT_TS} < u.t0_ts AND (event = {{target}}))) = 1"],
                [],
            ),
            (
                "ever_performed_event_uses_the_population_event_not_the_target",
                {"kind": "ever_performed_event", "event": "signup"},
                [f"HAVING max(({_EVENT_TS} < u.t0_ts AND event = {{popk_event}})) = 1"],
                ["AND (event = {target}))) = 1"],
            ),
            (
                "performed_within_days_window_ends_at_t0",
                {"kind": "performed_event_within_days", "days": 30},
                [f"HAVING max(({_EVENT_TS} >= u.t0_ts - {{popk_days}} * 86400 AND {_EVENT_TS} < u.t0_ts)) = 1"],
                ["toIntervalDay({popk_days})"],
            ),
            (
                "first_seen_window_ends_at_t0",
                {"kind": "person_first_seen_within_days", "days": 14},
                ["HAVING min(toInt(toUnixTimestamp(e.person.created_at))) >= u.t0_ts - {popk_days} * 86400"],
                ["toIntervalDay({popk_days})"],
            ),
            (
                "event_property_filter_at_t0_person_filter_at_the_scan",
                {
                    "properties": [
                        {"key": "plan", "type": "event", "operator": "exact", "value": "pro"},
                        {"key": "email", "type": "person", "operator": "is_set"},
                    ]
                },
                [
                    "AND (isNotNull(person.properties[{pop_k_1}]) AND person.properties[{pop_k_1}] != '') AND person.is_identified",
                    f"HAVING max(({_EVENT_TS} < u.t0_ts AND (properties[{{pop_k_0}}] = {{pop_0}}))) = 1",
                ],
                ["AND (properties[{pop_k_0}] = {pop_0}) AND person.is_identified"],
            ),
        ]
    )
    def test_membership_is_decided_per_user_at_t0(
        self, _name: str, training_population: dict[str, Any], expected: list[str], forbidden: list[str]
    ) -> None:
        cte, _values = _build_labeled_users_cte(
            target_event="feature_used",
            target_definition=None,
            team=None,
            horizon_days=7,
            lookback_days=90,
            training_population=training_population,
            sample_limit=None,
        )
        for fragment in expected:
            self.assertIn(fragment, cte)
        for fragment in forbidden:
            self.assertNotIn(fragment, cte)

    def test_t0_position_does_not_depend_on_a_moving_modulo(self) -> None:
        cte, _values = _build_labeled_users_cte(
            target_event="checkout",
            target_definition=None,
            team=None,
            horizon_days=7,
            lookback_days=90,
            training_population=None,
            sample_limit=None,
        )
        self.assertIn(
            "intDiv((cutoff_ts - first_ts) * toInt(bitAnd(cityHash64(toString(person_id)), 2147483647)), 2147483648)",
            cte,
        )
        self.assertNotIn("% (cutoff_ts - first_ts)", cte)


_DAILY_PAGEVIEWS = [("$pageview", days_ago) for days_ago in range(100, 0, -1)]


class TestAnchoredPopulationsAgainstClickhouse(ClickhouseTestMixin, APIBaseTest):
    # Executes the labeler for each population shape so the per-user-at-T0 HAVING
    # predicates are proven to resolve against the events scan, not only to print.

    @parameterized.expand(
        [
            (
                # Every T0 precedes the cutoff (now - horizon), so an adoption three days ago is after
                # T0, while a target on the user's first day precedes every possible T0.
                "adoption_keeps_users_who_adopt_after_t0",
                {"kind": "active_not_performed_target", "active_within_days": 30},
                {
                    "adopter": [*_DAILY_PAGEVIEWS, ("feature_used", 3)],
                    "prior_user": [("feature_used", 100), *_DAILY_PAGEVIEWS],
                },
                1,
            ),
            (
                "repeat_target_requires_prior_performance",
                {"kind": "ever_performed_target"},
                {"repeater": [("feature_used", 100), *_DAILY_PAGEVIEWS], "never": _DAILY_PAGEVIEWS},
                1,
            ),
            (
                "performed_within_days",
                {"kind": "performed_event_within_days", "days": 30, "event": "$pageview"},
                {"member": _DAILY_PAGEVIEWS},
                1,
            ),
            ("first_seen", {"kind": "person_first_seen_within_days", "days": 14}, {"member": _DAILY_PAGEVIEWS}, 1),
            (
                "event_property",
                {"properties": [{"key": "plan", "type": "event", "operator": "exact", "value": "pro"}]},
                {"member": _DAILY_PAGEVIEWS},
                1,
            ),
        ]
    )
    def test_anchored_population_executes_with_expected_membership(
        self, _name: str, training_population: dict[str, Any], users: dict[str, list[tuple[str, int]]], expected: int
    ) -> None:
        for distinct_id, events in users.items():
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], is_identified=True)
            for event, days_ago in events:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=timezone.now() - timedelta(days=days_ago),
                    properties={"plan": "pro"},
                )
        flush_persons_and_events()

        sql, values = build_random_t0_labeler_sql(
            target_event="feature_used",
            horizon_days=7,
            lookback_days=120,
            training_population=training_population,
            team=self.team,
        )
        rows = run_hogql_rows(
            team=self.team,
            query=HogQLQuery(query=sql, values=values),
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        )
        assert int(rows[0][0]) == expected
