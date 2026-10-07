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
    LABELER_QUERY_MODIFIERS,
    PREDICTION_EVENT_NAME,
    ROLLING_SCORE_LIMIT,
    RollingSelection,
    TrainingSample,
    TrainingSampleTooLarge,
    _build_labeled_users_cte,
    _build_population_kind_conditions,
    _compile_population_filters,
    _substitute_anchors,
    build_eligible_count_sql,
    build_inference_anchors_sql,
    build_inference_features_sql,
    build_random_t0_labeler_sql,
    build_training_features_sql,
    rolling_rescore_runs,
    rolling_selection,
    strip_sql_comments,
    utc_day_start,
)
from products.autoresearch.backend.query import run_hogql_rows


class TestStripSqlComments(BaseTest):
    @parameterized.expand(
        [
            ("line_comment", "SELECT a -- the count\nFROM t", "SELECT a \nFROM t"),
            ("block_comment", "SELECT a /* inline */ FROM t", "SELECT a   FROM t"),
            ("trailing_line_comment", "SELECT a FROM t -- trailing", "SELECT a FROM t "),
            ("double_slash_line_comment", "SELECT a // the count\nFROM t", "SELECT a \nFROM t"),
            ("no_comment", "SELECT a FROM t", "SELECT a FROM t"),
        ]
    )
    def test_strips_comments(self, _name: str, sql: str, expected: str) -> None:
        self.assertEqual(strip_sql_comments(sql), expected)

    @parameterized.expand(
        [
            ("double_dash_inside_string_literal", "SELECT 'a -- b' AS x FROM t"),
            ("doubled_quote_inside_string", "SELECT 'it''s -- fine' AS x FROM t"),
            ("backslash_quote_inside_string", "SELECT 'it\\'s -- fine' AS x FROM t"),
            ("block_comment_markers_inside_string", "SELECT '/* not a comment */' AS x FROM t"),
            ("double_dash_inside_backtick_identifier", "SELECT `weird--name` FROM t"),
            # An unbalanced quote runs to the end of the text. Stripping the rest as a comment
            # would replace the parse error the author needs to see with a different one.
            ("unterminated_string_literal", "SELECT 'oops -- x"),
        ]
    )
    def test_preserves_literals(self, _name: str, sql: str) -> None:
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

    def test_placeholder_inside_a_string_literal_is_a_value(self) -> None:
        feature_sql = "SELECT a.person_id AS distinct_id, '{anchors}' AS source FROM {anchors} a"
        result = _substitute_anchors(feature_sql, "(SELECT 1)")
        self.assertEqual(result, "SELECT a.person_id AS distinct_id, '{anchors}' AS source FROM (SELECT 1) a")

    def test_trailing_statement_terminator_is_dropped(self) -> None:
        # The training path nests the feature SQL as a derived table, where a `;` ends the statement early.
        result = _substitute_anchors("SELECT a.person_id AS distinct_id FROM {anchors} a;\n", "(SELECT 1)")
        self.assertEqual(result, "SELECT a.person_id AS distinct_id FROM (SELECT 1) a")


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


class TestRollingSelection(SimpleTestCase):
    @parameterized.expand(
        [
            ("at_the_cap", 50_000, 1),
            ("one_cycle_past_the_minimum_window", 1_400_000, 1),
            ("huge", 9_000_000, 1),
            ("weekly_cadence", 1_400_000, 7),
        ]
    )
    def test_score_history_window_outlasts_a_full_cycle(self, _name: str, eligible: int, cadence_days: int) -> None:
        rolling = rolling_selection(eligible=eligible, pipeline_id="p", cadence_days=cadence_days)
        assert rolling is not None
        assert rolling.limit == ROLLING_SCORE_LIMIT
        cycle_days = rolling_rescore_runs(eligible=eligible, scored=rolling.limit) * cadence_days
        assert rolling.scored_lookback_days > cycle_days

    def test_a_population_below_the_cap_scores_whole(self) -> None:
        assert rolling_selection(eligible=49_999, pipeline_id="p", cadence_days=1) is None


class TestPopulationFilterCompilation(SimpleTestCase):
    # A filter that cannot be compiled must raise: skipping it would silently widen the
    # population, and inference writes person properties for everyone it scores.

    @parameterized.expand(
        [
            ("cohort_type", [{"key": "id", "type": "cohort", "operator": "exact", "value": 123}]),
            ("unknown_operator", [{"key": "plan", "type": "person", "operator": "regex", "value": "x"}]),
            ("missing_key", [{"type": "person", "operator": "is_set"}]),
            ("missing_type", [{"key": "plan", "operator": "exact", "value": "pro"}]),
            ("non_numeric_threshold", [{"key": "price", "type": "event", "operator": "gt", "value": "cheap"}]),
            # An operator the operator tables cannot hash must still take the ValueError path.
            ("list_operator", [{"key": "plan", "type": "person", "operator": ["exact"], "value": "pro"}]),
            ("dict_operator", [{"key": "plan", "type": "person", "operator": {"op": "exact"}, "value": "pro"}]),
        ]
    )
    def test_uncompilable_filter_raises_instead_of_widening(self, _name: str, properties: list[dict[str, Any]]) -> None:
        with self.assertRaises(ValueError):
            _compile_population_filters(properties)

    @parameterized.expand(
        [
            # is_set follows the canonical property compiler: an empty string is a set value.
            ("is_set", {"operator": "is_set"}, "isNotNull(properties[{pop_k_0}])", {}),
            ("is_not_set", {"operator": "is_not_set"}, "isNull(properties[{pop_k_0}])", {}),
            (
                "icontains_list_matches_any",
                {"operator": "icontains", "value": ["pro", "enterprise"]},
                "(properties[{pop_k_0}] ILIKE {pop_0_0} OR properties[{pop_k_0}] ILIKE {pop_0_1})",
                {"pop_0_0": "%pro%", "pop_0_1": "%enterprise%"},
            ),
            (
                "not_icontains_list_excludes_every",
                {"operator": "not_icontains", "value": ["pro", "enterprise"]},
                "(properties[{pop_k_0}] NOT ILIKE {pop_0_0} AND properties[{pop_k_0}] NOT ILIKE {pop_0_1})",
                {"pop_0_0": "%pro%", "pop_0_1": "%enterprise%"},
            ),
            (
                "exact_list_is_an_in_clause",
                {"operator": "exact", "value": ["pro", "enterprise"]},
                "properties[{pop_k_0}] IN ({pop_0_0}, {pop_0_1})",
                {"pop_0_0": "pro", "pop_0_1": "enterprise"},
            ),
            (
                "is_not_list_is_a_not_in_clause",
                {"operator": "is_not", "value": ["pro", "enterprise"]},
                "properties[{pop_k_0}] NOT IN ({pop_0_0}, {pop_0_1})",
                {"pop_0_0": "pro", "pop_0_1": "enterprise"},
            ),
            (
                "string_threshold_is_bound_as_a_number",
                {"operator": "gte", "value": "13"},
                "toFloat64OrNull(properties[{pop_k_0}]) >= {pop_0}",
                {"pop_0": 13.0},
            ),
        ]
    )
    def test_compiles_operator(
        self, _name: str, filter_fields: dict[str, Any], expected_part: str, expected_values: dict[str, Any]
    ) -> None:
        compiled = _compile_population_filters([{"key": "plan", "type": "person", **filter_fields}])
        self.assertEqual(compiled.person_parts, [expected_part])
        self.assertEqual({k: v for k, v in compiled.values.items() if k != "pop_k_0"}, expected_values)

    def test_hostile_key_is_bound_not_interpolated(self) -> None:
        # Keys are bound as HogQL values, so a hostile key must never reach the SQL text.
        hostile_key = "'; DROP TABLE users; --"
        compiled = _compile_population_filters([{"key": hostile_key, "type": "person", "operator": "is_set"}])
        self.assertEqual(len(compiled.person_parts), 1)
        self.assertNotIn(hostile_key, compiled.person_parts[0])
        self.assertEqual(compiled.values["pop_k_0"], hostile_key)

    @parameterized.expand(
        [
            ("empty_allowlist_matches_nobody", "exact", ["1 = 0"]),
            ("empty_denylist_excludes_nobody", "is_not", []),
            ("empty_substring_allowlist_matches_nobody", "icontains", ["1 = 0"]),
            ("empty_substring_denylist_excludes_nobody", "not_icontains", []),
        ]
    )
    def test_empty_value_list(self, _name: str, operator: str, expected_parts: list[str]) -> None:
        compiled = _compile_population_filters([{"key": "plan", "type": "person", "operator": operator, "value": []}])
        self.assertEqual(compiled.person_parts, expected_parts)


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
                ["argMax(ifNull((created_at >= now() - toIntervalDay({popk_days})), 0), version) = 1"],
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

    @parameterized.expand(
        [
            (
                "inference_anchors",
                lambda: build_inference_anchors_sql(lookback_days=90, inference_population={})[0],
            ),
            (
                "eligible_count",
                lambda: build_eligible_count_sql(horizon_days=7, lookback_days=90, training_population={})[0],
            ),
            (
                "labeler_user_window",
                lambda: build_random_t0_labeler_sql(
                    target_event="x", horizon_days=7, lookback_days=90, training_population={}
                )[0],
            ),
            (
                "labeler_labeled_users_aggregate",
                lambda: build_random_t0_labeler_sql(
                    target_event="x", horizon_days=7, lookback_days=90, training_population={}
                )[0].split("labeled_users AS")[1],
            ),
            (
                "kind_membership_subquery",
                lambda: build_inference_anchors_sql(
                    lookback_days=90, inference_population={"kind": "performed_event_within_days", "days": 30}
                )[0],
            ),
        ]
    )
    def test_activity_scans_exclude_the_prediction_event(self, _name: str, build) -> None:
        # Every live cadence writes one autoresearch_prediction per scored person; a scan that
        # counted it kept a person eligible forever on nothing but their own predictions.
        self.assertIn(f"event != '{PREDICTION_EVENT_NAME}'", build())

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
                    f"ifNull(max(({_EVENT_TS} < u.t0_ts AND (event = {{target}}))), 0) = 0",
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
                ["HAVING min(u.person_created_ts) >= u.t0_ts - {popk_days} * 86400"],
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
                    "argMax(is_identified, version) = 1 AND argMax(ifNull((isNotNull(properties[{pop_k_1}])), 0), version) = 1",
                    f"HAVING max(({_EVENT_TS} < u.t0_ts AND (properties[{{pop_k_0}}] = {{pop_0}}))) = 1",
                ],
                ["argMax(ifNull((properties[{pop_k_0}] = {pop_0})", "person."],
            ),
            (
                # Inference ANDs event filters on one row, so training must find one pre-T0 event
                # that satisfies all of them, not one event per filter.
                "event_property_filters_are_satisfied_by_one_event",
                {
                    "properties": [
                        {"key": "plan", "type": "event", "operator": "exact", "value": "pro"},
                        {"key": "country", "type": "event", "operator": "exact", "value": "US"},
                    ]
                },
                [
                    f"HAVING max(({_EVENT_TS} < u.t0_ts AND (properties[{{pop_k_0}}] = {{pop_0}}"
                    " AND properties[{pop_k_1}] = {pop_1}))) = 1"
                ],
                ["= 1 AND max("],
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

    def test_bound_anchor_replaces_every_now(self) -> None:
        cte, values = _build_labeled_users_cte(
            target_event="checkout",
            target_definition=None,
            team=None,
            horizon_days=7,
            lookback_days=90,
            training_population={"kind": "ever_performed_event", "event": "signed_up"},
            sample_limit=None,
            anchor_ts=1_700_000_000,
        )
        self.assertNotIn("now()", cte)
        self.assertIn("fromUnixTimestamp({anchor_ts})", cte)
        self.assertEqual(values["anchor_ts"], 1_699_920_000)

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
            "intDiv((cutoff_day - first_day + 1) * toInt(bitAnd(cityHash64(toString(person_id)), 2147483647)), 2147483648)",
            cte,
        )
        self.assertNotIn("% (cutoff_day - first_day", cte)


_DAILY_PAGEVIEWS = [("$pageview", days_ago) for days_ago in range(100, 0, -1)]


class TestTrainingSamplePlan(SimpleTestCase):
    @parameterized.expand(
        [
            ("fits_the_budget", 40, 4, 1.0, 40),
            ("all_positives", 100, 100, 1.0, 100),
            ("above_the_budget", 1_000, 100, 0.1, 190),
        ]
    )
    def test_plan_keeps_every_positive_and_fills_the_budget_with_negatives(
        self, _name: str, population: int, positives: int, rate: float, size: int
    ) -> None:
        sample = TrainingSample.plan(population=population, positives=positives, budget=190)
        assert sample.negative_sample_rate == rate
        assert sample.expected_size == size

    def test_plan_refuses_positives_that_alone_exceed_the_budget(self) -> None:
        with self.assertRaises(TrainingSampleTooLarge):
            TrainingSample.plan(population=1_000, positives=200, budget=190)


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
            (
                "person_property",
                {"properties": [{"key": "tier", "type": "person", "operator": "exact", "value": "pro"}]},
                {"member": _DAILY_PAGEVIEWS, "other_tier": _DAILY_PAGEVIEWS},
                1,
                None,
                {"member": {"tier": "pro"}, "other_tier": {"tier": "free"}},
            ),
            (
                "identified_only",
                {},
                {"member": _DAILY_PAGEVIEWS, "anonymous": _DAILY_PAGEVIEWS},
                1,
                None,
                {},
                {"anonymous"},
            ),
            (
                # T0 falls in [first signup, now - horizon), after every target event, so the label is 0.
                # A span from the first event of any kind would place most T0s among the targets.
                "t0_spans_from_the_first_population_event",
                {"kind": "ever_performed_event", "event": "signup"},
                {
                    "member": [
                        *_DAILY_PAGEVIEWS,
                        *[("feature_used", days_ago) for days_ago in range(100, 20, -1)],
                        *[("signup", days_ago) for days_ago in range(20, 0, -1)],
                    ]
                },
                1,
                0,
            ),
        ]
    )
    def test_anchored_population_executes_with_expected_membership(
        self,
        _name: str,
        training_population: dict[str, Any],
        users: dict[str, list[tuple[str, int]]],
        expected: int,
        expected_positives: int | None = None,
        person_properties: dict[str, dict[str, Any]] | None = None,
        anonymous: set[str] | None = None,
    ) -> None:
        now = timezone.now()  # nosemgrep: test-datetime-now-without-freeze (must match ClickHouse server-side now())
        for distinct_id, events in users.items():
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[distinct_id],
                is_identified=distinct_id not in (anonymous or set()),
                properties=(person_properties or {}).get(distinct_id, {}),
            )
            for event, days_ago in events:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=now - timedelta(days=days_ago),
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
            query=HogQLQuery(query=sql, values=values, modifiers=LABELER_QUERY_MODIFIERS),
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        )
        assert int(rows[0][0]) == expected
        if expected_positives is not None:
            assert int(rows[0][1]) == expected_positives

    @parameterized.expand([("one_day", 1), ("three_days", 3), ("seven_days", 7)])
    def test_every_t0_is_a_utc_midnight_that_does_not_move_within_the_anchor_day(
        self, _name: str, horizon_days: int
    ) -> None:
        now = timezone.now()  # nosemgrep: test-datetime-now-without-freeze (must match ClickHouse server-side now())
        day_start = utc_day_start(int(now.timestamp()))
        first_event_ts: dict[str, int] = {}
        for i in range(20):
            distinct_id = f"user_{i}"
            person = _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], is_identified=True)
            for days_ago in range(40 - i, 0, -1):
                timestamp = now - timedelta(days=days_ago, hours=5, minutes=i)
                _create_event(team=self.team, event="$pageview", distinct_id=distinct_id, timestamp=timestamp)
            first_event_ts[str(person.uuid)] = int((now - timedelta(days=40 - i, hours=5, minutes=i)).timestamp())
        flush_persons_and_events()

        def t0s(anchor_ts: int) -> dict[str, int]:
            cte, values = _build_labeled_users_cte(
                target_event="feature_used",
                target_definition=None,
                team=self.team,
                horizon_days=horizon_days,
                lookback_days=90,
                training_population=None,
                sample_limit=None,
                anchor_ts=anchor_ts,
            )
            rows = run_hogql_rows(
                team=self.team,
                query=HogQLQuery(
                    query=f"{cte} SELECT person_id, t0_ts FROM labeled_users",
                    values=values,
                    modifiers=LABELER_QUERY_MODIFIERS,
                ),
                execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            )
            return {str(person_id): int(t0_ts) for person_id, t0_ts in rows}

        morning = t0s(day_start - 86400 + 2 * 3600)
        afternoon = t0s(day_start - 86400 + 17 * 3600)

        assert len(morning) == 20
        assert afternoon == morning
        label_cutoff = day_start - 86400 - horizon_days * 86400
        for person_id, t0_ts in morning.items():
            assert t0_ts % 86400 == 0
            assert first_event_ts[person_id] < t0_ts <= label_cutoff

    def test_negative_sampling_keeps_every_positive_and_the_training_rows_match_the_count(self) -> None:
        now = timezone.now()  # nosemgrep: test-datetime-now-without-freeze (must match ClickHouse server-side now())
        positives = [f"positive_{i}" for i in range(3)]
        negatives = [f"negative_{i}" for i in range(40)]
        for distinct_id in positives + negatives:
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id], is_identified=True)
            for event, days_ago in _DAILY_PAGEVIEWS:
                _create_event(
                    team=self.team, event=event, distinct_id=distinct_id, timestamp=now - timedelta(days=days_ago)
                )
                if distinct_id in positives:
                    _create_event(
                        team=self.team,
                        event="feature_used",
                        distinct_id=distinct_id,
                        timestamp=now - timedelta(days=days_ago),
                    )
        flush_persons_and_events()
        common: dict[str, Any] = {
            "target_event": "feature_used",
            "horizon_days": 7,
            "lookback_days": 120,
            "training_population": None,
            "team": self.team,
            "negative_sample_rate": 0.25,
        }

        def run(sql: str, values: dict[str, Any]) -> list[Any]:
            return run_hogql_rows(
                team=self.team,
                query=HogQLQuery(query=sql, values=values, modifiers=LABELER_QUERY_MODIFIERS),
                execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            )

        [[eligible, sampled_positives]] = run(*build_random_t0_labeler_sql(**common))
        rows = run(
            *build_training_features_sql(
                feature_sql="SELECT a.person_id AS distinct_id, 1 AS one FROM {anchors} a", **common
            )
        )
        assert sampled_positives == len(positives)
        assert len(positives) < eligible < len(positives) + len(negatives)
        # Columns: distinct_id, one, __label, __fold.
        assert len(rows) == eligible
        assert sum(row[2] for row in rows) == len(positives)

    @parameterized.expand(
        [
            ("any_event_population", None),
            ("population_event_member_scan", {"kind": "ever_performed_event", "event": "$pageview"}),
        ]
    )
    def test_row_mode_counts_read_identity_and_person_filters_from_raw_persons(
        self, _name: str, kind: dict[str, Any] | None
    ) -> None:
        now = timezone.now()  # nosemgrep: test-datetime-now-without-freeze (must match ClickHouse server-side now())
        for distinct_id, tier, identified in [("pro", "pro", True), ("free", "free", True), ("anon_pro", "pro", False)]:
            _create_person(
                team_id=self.team.pk, distinct_ids=[distinct_id], is_identified=identified, properties={"tier": tier}
            )
            for _event, days_ago in _DAILY_PAGEVIEWS[-30:]:
                _create_event(
                    team=self.team, event="$pageview", distinct_id=distinct_id, timestamp=now - timedelta(days=days_ago)
                )
        flush_persons_and_events()
        population = {
            **(kind or {}),
            "properties": [{"key": "tier", "type": "person", "operator": "exact", "value": "pro"}],
        }

        def run(sql: str, values: dict[str, Any]) -> list[Any]:
            return run_hogql_rows(
                team=self.team,
                query=HogQLQuery(query=sql, values=values, modifiers=LABELER_QUERY_MODIFIERS),
                execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            )[0]

        eligible_sql, eligible_values = build_eligible_count_sql(
            horizon_days=7, lookback_days=90, training_population=population
        )
        anchors_sql, anchors_values = build_inference_anchors_sql(lookback_days=30, inference_population=population)
        assert [int(v) for v in run(eligible_sql, eligible_values)] == [1, 2]
        assert int(run(f"SELECT count() FROM ({anchors_sql.strip()})", anchors_values)[0]) == 1

    def test_rolling_selection_ranks_by_staleness_and_covers_everyone_in_ceil_m_over_n_runs(self) -> None:
        now = timezone.now()  # nosemgrep: test-datetime-now-without-freeze (must match ClickHouse server-side now())
        first_cutoff = now.replace(microsecond=0) - timedelta(days=3)
        pipeline_id = "11111111-1111-1111-1111-111111111111"
        # (days of activity before the first cutoff, days of this pipeline's last score before it)
        people: dict[str, tuple[int, int | None]] = {
            "active_never_scored": (1, None),
            "idle_never_scored": (5, None),
            "scored_by_another_pipeline": (3, None),
            "scored_long_ago": (1, 10),
            "scored_recently": (1, 2),
        }
        name_by_uuid: dict[str, str] = {}
        for name, (active_days_ago, scored_days_ago) in people.items():
            person = _create_person(team_id=self.team.pk, distinct_ids=[name], is_identified=True)
            name_by_uuid[str(person.uuid)] = name
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=name,
                timestamp=first_cutoff - timedelta(days=active_days_ago),
            )
            if scored_days_ago is not None:
                _create_event(
                    team=self.team,
                    event=PREDICTION_EVENT_NAME,
                    distinct_id=name,
                    timestamp=first_cutoff - timedelta(days=scored_days_ago),
                    properties={"$autoresearch_pipeline_id": pipeline_id},
                )
        _create_event(
            team=self.team,
            event=PREDICTION_EVENT_NAME,
            distinct_id="scored_by_another_pipeline",
            timestamp=first_cutoff - timedelta(days=1),
            properties={"$autoresearch_pipeline_id": "22222222-2222-2222-2222-222222222222"},
        )
        flush_persons_and_events()

        def select(cutoff: Any) -> list[str]:
            sql, values = build_inference_anchors_sql(
                lookback_days=30,
                inference_population={},
                cutoff_ts=int(cutoff.timestamp()),
                rolling=RollingSelection(pipeline_id=pipeline_id, limit=2, scored_lookback_days=30),
            )
            rows = run_hogql_rows(
                team=self.team,
                query=HogQLQuery(query=sql, values=values, modifiers=LABELER_QUERY_MODIFIERS),
                execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
            )
            return sorted(name_by_uuid[str(row[0])] for row in rows)

        selections: list[list[str]] = []
        for day in range(3):
            cutoff = first_cutoff + timedelta(days=day)
            selected = select(cutoff)
            assert select(cutoff) == selected
            selections.append(selected)
            for name in selected:
                _create_event(
                    team=self.team,
                    event=PREDICTION_EVENT_NAME,
                    distinct_id=name,
                    timestamp=cutoff + timedelta(hours=1),
                    properties={"$autoresearch_pipeline_id": pipeline_id},
                )
            flush_persons_and_events()

        assert selections == [
            ["active_never_scored", "scored_by_another_pipeline"],
            ["idle_never_scored", "scored_long_ago"],
            ["active_never_scored", "scored_recently"],
        ]
