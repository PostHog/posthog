from typing import ClassVar, Optional

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.database.database import Database

from products.data_modeling.backend.logic.incremental import IncrementalConfig
from products.data_modeling.backend.logic.incremental_eligibility import check_incremental_eligibility

DAY_KEY = IncrementalConfig(incremental_key="day", unique_key=("day",))
DAY_EVENT_KEY = IncrementalConfig(incremental_key="day", unique_key=("day", "event"))

GROUPED = "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day"


class TestIncrementalEligibility(BaseTest):
    @parameterized.expand(
        [
            ("grouped_by_key", GROUPED, DAY_KEY),
            (
                "unique_key_covers_all_grouping_columns",
                "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
                DAY_EVENT_KEY,
            ),
            (
                "grouping_repeats_the_expression_instead_of_the_alias",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY toStartOfDay(timestamp)",
                DAY_KEY,
            ),
            (
                "non_associative_aggregates_are_fine",
                "SELECT toStartOfDay(timestamp) AS day, count(DISTINCT person_id) AS people, "
                "quantileExact(0.5)(1) AS median FROM events GROUP BY day",
                DAY_KEY,
            ),
            (
                "row_level_model_with_no_grouping",
                "SELECT uuid, timestamp FROM events",
                IncrementalConfig(incremental_key="timestamp", unique_key=("uuid",)),
            ),
            (
                "group_by_all_with_a_covering_unique_key",
                "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY ALL",
                DAY_EVENT_KEY,
            ),
            (
                "order_by_in_a_subquery_is_a_no_op_without_a_limit",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM "
                "(SELECT timestamp FROM events ORDER BY timestamp) GROUP BY day",
                DAY_KEY,
            ),
            (
                "distinct_in_a_subquery_commutes_with_the_window_filter",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM "
                "(SELECT DISTINCT timestamp FROM events) GROUP BY day",
                DAY_KEY,
            ),
            (
                "limit_in_a_scalar_where_subquery_is_value_drift_not_a_row_source",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events "
                "WHERE timestamp > (SELECT min(timestamp) FROM events LIMIT 1) GROUP BY day",
                DAY_KEY,
            ),
            (
                "limit_in_an_in_subquery_is_value_drift_not_a_row_source",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events "
                "WHERE event IN (SELECT event FROM events LIMIT 10) GROUP BY day",
                DAY_KEY,
            ),
            (
                "limit_in_a_column_cte_is_a_scalar_not_a_row_source",
                "WITH (SELECT min(timestamp) FROM events LIMIT 1) AS m "
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events WHERE timestamp > m GROUP BY day",
                DAY_KEY,
            ),
        ]
    )
    def test_eligible(self, _name: str, query: str, config: IncrementalConfig) -> None:
        result = check_incremental_eligibility(query, config)
        assert result.eligible, result.blockers

    @parameterized.expand(
        [
            (
                "unique_key_misses_a_grouping_column",
                "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
                DAY_KEY,
                "must include every GROUP BY column",
            ),
            (
                "key_is_an_aggregate",
                "SELECT max(timestamp) AS day, count() AS c FROM events",
                DAY_KEY,
                "is an aggregate",
            ),
            (
                "key_not_in_output",
                "SELECT event, count() AS c FROM events GROUP BY event",
                DAY_KEY,
                "not one of this query's output columns",
            ),
            (
                "key_is_not_among_the_grouping_columns",
                "SELECT toStartOfDay(timestamp) AS day, toStartOfHour(timestamp) AS hour, count() AS c "
                "FROM events GROUP BY day",
                IncrementalConfig(incremental_key="hour", unique_key=("day",)),
                "must be one of the GROUP BY columns",
            ),
            ("top_level_limit", f"{GROUPED} LIMIT 10", DAY_KEY, "LIMIT cannot be incremental"),
            ("top_level_order_by", f"{GROUPED} ORDER BY day", DAY_KEY, "ORDER BY"),
            (
                "distinct_without_grouping",
                "SELECT DISTINCT toStartOfDay(timestamp) AS day FROM events",
                DAY_KEY,
                "SELECT DISTINCT",
            ),
            (
                "except_set_operation",
                f"{GROUPED} EXCEPT {GROUPED}",
                DAY_KEY,
                "cannot be incremental",
            ),
            (
                "window_function",
                "SELECT toStartOfDay(timestamp) AS day, row_number() OVER (ORDER BY timestamp) AS rn "
                "FROM events GROUP BY day, timestamp",
                DAY_EVENT_KEY,
                "Window functions",
            ),
            ("unparseable", "SELECT FROM WHERE", DAY_KEY, "could not be parsed"),
            (
                # GROUP BY ALL carries no explicit entries, so a check reading only `group_by`
                # would treat this as ungrouped and let an uncovered key through.
                "group_by_all_unique_key_misses_a_column",
                "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY ALL",
                DAY_KEY,
                "must include every GROUP BY column",
            ),
            (
                # A group can pass the condition on one run and fail it on the next; the upsert
                # never deletes, so the stale row would stay forever.
                "having_on_the_outer_select",
                f"{GROUPED} HAVING count() > 0",
                DAY_KEY,
                "HAVING",
            ),
            (
                "having_in_a_cte",
                "WITH t AS (SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events "
                "GROUP BY day HAVING count() > 0) SELECT day, c FROM t",
                DAY_KEY,
                "HAVING",
            ),
            (
                "limit_in_a_cte",
                "WITH t AS (SELECT timestamp FROM events LIMIT 100) "
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM t GROUP BY day",
                DAY_KEY,
                "LIMIT inside a subquery or CTE",
            ),
            (
                "limit_in_a_from_subquery",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM "
                "(SELECT timestamp FROM events LIMIT 100) GROUP BY day",
                DAY_KEY,
                "LIMIT inside a subquery or CTE",
            ),
            (
                "limit_in_a_join_source",
                "SELECT toStartOfDay(e.timestamp) AS day, count() AS c FROM events e "
                "JOIN (SELECT distinct_id FROM events LIMIT 10) x ON e.distinct_id = x.distinct_id GROUP BY day",
                DAY_KEY,
                "LIMIT inside a subquery or CTE",
            ),
            (
                "limit_two_subquery_levels_down",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM "
                "(SELECT timestamp FROM (SELECT timestamp FROM events LIMIT 100)) GROUP BY day",
                DAY_KEY,
                "LIMIT inside a subquery or CTE",
            ),
            (
                "offset_in_a_subquery",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM "
                "(SELECT timestamp FROM events OFFSET 5) GROUP BY day",
                DAY_KEY,
                "OFFSET inside a subquery or CTE",
            ),
            (
                "limit_by_in_a_subquery",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM "
                "(SELECT timestamp, event FROM events LIMIT 1 BY event) GROUP BY day",
                DAY_KEY,
                "LIMIT BY inside a subquery or CTE",
            ),
            (
                # The row_number over full history changes for already-written rows as data
                # arrives, and those rows are never rewritten.
                "window_function_in_a_cte",
                "WITH t AS (SELECT timestamp, row_number() OVER (ORDER BY timestamp) AS rn FROM events) "
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM t GROUP BY day",
                DAY_KEY,
                "Window functions",
            ),
            (
                "except_inside_a_subquery",
                f"SELECT day, c FROM (({GROUPED}) EXCEPT ({GROUPED}))",
                DAY_KEY,
                "EXCEPT",
            ),
            (
                "rollup_in_a_subquery",
                "SELECT day, c FROM (SELECT toStartOfDay(timestamp) AS day, count() AS c "
                "FROM events GROUP BY ROLLUP(day))",
                DAY_KEY,
                "GROUP BY ROLLUP",
            ),
        ]
    )
    def test_blocked(self, _name: str, query: str, config: IncrementalConfig, expected: str) -> None:
        result = check_incremental_eligibility(query, config)
        assert not result.eligible
        assert any(expected in blocker for blocker in result.blockers), result.blockers

    def test_nullable_unique_key_is_blocked(self) -> None:
        """A null key never matches, so the upsert inserts instead of updating and the table gains
        a duplicate on every run, with nothing failing. Worth catching before the first run."""
        result = check_incremental_eligibility(
            GROUPED, DAY_KEY, column_types={"day": "Nullable(DateTime)", "c": "UInt64"}
        )

        assert not result.eligible
        assert any("can be null" in blocker for blocker in result.blockers), result.blockers

    def test_non_deterministic_function_warns_without_blocking(self) -> None:
        result = check_incremental_eligibility(
            "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events WHERE timestamp < now() GROUP BY day",
            DAY_KEY,
        )

        assert result.eligible
        assert any("now()" in warning for warning in result.warnings), result.warnings

    def test_key_behind_an_aggregating_cte_warns_that_it_will_not_prune(self) -> None:
        """The filter still lands in the outer WHERE, so the result is correct, but ClickHouse
        cannot push it through the inner GROUP BY and the run reads as much as a full refresh."""
        result = check_incremental_eligibility(
            "WITH daily AS (SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day) "
            "SELECT day, c FROM daily",
            IncrementalConfig(incremental_key="day", unique_key=("day",)),
        )

        assert result.eligible
        assert any("cannot be pushed down" in warning for warning in result.warnings), result.warnings

    def test_candidates_exclude_aggregates_and_span_union_branches(self) -> None:
        result = check_incremental_eligibility(
            "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event "
            "UNION ALL "
            "SELECT toStartOfDay(timestamp) AS day, 'other' AS other, count() AS c FROM events GROUP BY day",
            None,
        )

        assert result.key_candidates == ["day"]

    def test_the_same_construct_in_several_sources_reads_as_one_blocker(self) -> None:
        result = check_incremental_eligibility(
            "WITH a AS (SELECT timestamp FROM events LIMIT 10), b AS (SELECT timestamp FROM events LIMIT 10) "
            "SELECT toStartOfDay(a.timestamp) AS day, count() AS c FROM a JOIN b ON a.timestamp = b.timestamp "
            "GROUP BY day",
            DAY_KEY,
        )

        assert not result.eligible
        assert len(result.blockers) == 1, result.blockers


class TestStarExpansion:
    database: ClassVar[Database]

    @classmethod
    def setup_class(cls) -> None:
        cls.database = Database()

    def _check(self, query: str, config: Optional[IncrementalConfig] = None, *, database: Optional[Database] = None):
        return check_incremental_eligibility(query, config, database=database or self.database)

    def test_star_over_a_table_expands_to_real_columns(self) -> None:
        result = self._check("SELECT * FROM events")

        assert "timestamp" in result.key_candidates
        assert "*" not in result.key_candidates

    def test_aliased_star_expands_too(self) -> None:
        result = self._check("SELECT e.* FROM events e")

        assert "timestamp" in result.key_candidates
        assert "*" not in result.key_candidates

    def test_expanded_candidates_still_intersect_union_branches(self) -> None:
        result = self._check("SELECT * FROM (SELECT 1 AS a, 2 AS b) UNION ALL SELECT 3 AS a, 4 AS c")

        assert result.key_candidates == ["a"]

    def test_an_aggregate_alongside_a_star_stays_excluded(self) -> None:
        result = self._check("SELECT *, count() AS c FROM events GROUP BY ALL")

        assert "timestamp" in result.key_candidates
        assert "c" not in result.key_candidates

    def test_key_candidates_carry_coarse_types(self) -> None:
        # Raw table columns must resolve through their schema DatabaseField: the constant-type
        # route alone left most of the events table untagged.
        result = self._check("SELECT event, timestamp, uuid, properties FROM events")

        assert result.key_candidate_types["timestamp"] == "datetime"
        assert result.key_candidate_types["event"] == "string"
        assert result.key_candidate_types["uuid"] == "uuid"
        assert result.key_candidate_types["properties"] == "json"

    def test_schema_expression_fields_are_typed_too(self) -> None:
        # person_id is an ExpressionField whose inner expression stays untyped in the hogql
        # dialect; without on-demand resolution it reads as unknown and slips into the key picker.
        result = self._check("SELECT person_id, timestamp FROM events")

        assert "person_id" in result.key_candidate_types
        assert "person_id" not in result.key_candidates
        assert "person_id" in result.unique_key_candidates

    @parameterized.expand(
        [
            ("boolean", "SELECT timestamp, timestamp > now() AS flag FROM events", "flag"),
            ("array", "SELECT timestamp, [1, 2] AS xs FROM events", "xs"),
            ("tuple", "SELECT timestamp, (1, 2) AS pair FROM events", "pair"),
            ("string", "SELECT timestamp, event FROM events", "event"),
            ("uuid", "SELECT timestamp, uuid FROM events", "uuid"),
            ("json", "SELECT timestamp, properties FROM events", "properties"),
        ]
    )
    def test_columns_that_cannot_track_new_rows_are_not_key_candidates(
        self, _name: str, query: str, column: str
    ) -> None:
        result = self._check(query)

        assert column not in result.key_candidates
        assert "timestamp" in result.key_candidates

    def test_strings_and_uuids_stay_available_for_the_unique_key(self) -> None:
        # A grouped query's unique key must cover every GROUP BY column, and those are often
        # strings - excluding them here would make such queries impossible to configure. UUIDs
        # identify rows, which is equality, so they qualify too.
        result = self._check(
            "SELECT toStartOfDay(timestamp) AS day, event, any(uuid) AS id, count() AS c "
            "FROM events GROUP BY day, event"
        )

        assert "event" not in result.key_candidates
        assert "event" in result.unique_key_candidates
        assert "day" in result.unique_key_candidates
        assert "c" not in result.unique_key_candidates

        flat = self._check("SELECT timestamp, uuid FROM events")
        assert "uuid" in flat.unique_key_candidates
        assert "uuid" not in flat.key_candidates

    def test_without_a_database_types_are_unknown_and_nothing_is_filtered(self) -> None:
        result = check_incremental_eligibility("SELECT timestamp, flag FROM events", None)

        assert result.key_candidate_types == {}
        assert "flag" in result.key_candidates
        assert result.unique_key_candidates == result.key_candidates

    @parameterized.expand(
        [
            ("no_database", "SELECT * FROM events", False),
            ("unresolvable_table", "SELECT * FROM definitely_not_a_table", True),
        ]
    )
    def test_falls_back_to_the_raw_asterisk_when_expansion_is_unavailable(
        self, _name: str, query: str, use_database: bool
    ) -> None:
        result = check_incremental_eligibility(query, None, database=self.database if use_database else None)

        assert result.key_candidates == ["*"]

    def test_a_config_naming_an_expanded_column_passes(self) -> None:
        result = self._check(
            "SELECT * FROM events", IncrementalConfig(incremental_key="timestamp", unique_key=("uuid",))
        )

        assert result.eligible, result.blockers

    def test_without_a_database_a_config_on_a_star_query_passes_the_key_check(self) -> None:
        # The star passes the key through, and the window filter resolves it by name the same way
        # at run time - so blocking here would reject a config the runtime can actually serve.
        result = check_incremental_eligibility(
            "SELECT * FROM events", IncrementalConfig(incremental_key="timestamp", unique_key=("uuid",))
        )

        assert result.eligible, result.blockers

    def test_grouping_columns_survive_resolution_for_the_coverage_check(self) -> None:
        # The resolver rewrites `GROUP BY event` into an Alias node; if that form is not
        # recognized, the column vanishes from the grouping set and an uncovered unique key passes.
        result = self._check(
            "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
            DAY_KEY,
        )

        assert not result.eligible
        assert any("must include every GROUP BY column" in blocker for blocker in result.blockers), result.blockers

    def test_grouping_by_the_inline_expression_still_matches_its_alias_on_the_resolved_ast(self) -> None:
        result = self._check(
            "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY toStartOfDay(timestamp)",
            DAY_KEY,
        )

        assert result.eligible, result.blockers

    def test_the_aggregating_cte_pushdown_warning_survives_resolution(self) -> None:
        result = self._check(
            "WITH daily AS (SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day) "
            "SELECT day, c FROM daily",
            DAY_KEY,
        )

        assert result.eligible
        assert any("cannot be pushed down" in warning for warning in result.warnings), result.warnings
