from typing import ClassVar, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DateTimeDatabaseField, IntegerDatabaseField, SavedQuery, TableNode

from products.data_modeling.backend.logic.incremental import IncrementalConfig
from products.data_modeling.backend.logic.incremental_eligibility import (
    check_incremental_eligibility,
    propose_incremental_config,
)

DAY_KEY = IncrementalConfig(incremental_key="day", unique_key=("day",))
DAY_EVENT_KEY = IncrementalConfig(incremental_key="day", unique_key=("day", "event"))

GROUPED = "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day"


class TestIncrementalEligibility(SimpleTestCase):
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
                "unique_key_is_empty",
                "SELECT timestamp FROM events",
                IncrementalConfig(incremental_key="timestamp", unique_key=()),
                "at least one unique key column",
            ),
            (
                "unique_key_includes_an_aggregate",
                GROUPED,
                IncrementalConfig(incremental_key="day", unique_key=("day", "c")),
                "is an aggregate",
            ),
            (
                "unique_key_includes_an_alias_of_an_aggregate",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c, c + 1 AS revision FROM events GROUP BY day",
                IncrementalConfig(incremental_key="day", unique_key=("day", "revision")),
                "is an aggregate",
            ),
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

    @parameterized.expand(
        [
            ("limit", "SELECT id AS team_id_, 1 AS has_views FROM events LIMIT 50000", "LIMIT"),
            (
                "having",
                "SELECT toStartOfDay(timestamp) AS team_id_, count() AS has_views FROM events "
                "GROUP BY team_id_ HAVING count() > 0",
                "HAVING",
            ),
        ]
    )
    def test_a_blocked_shape_behind_a_saved_query_reference_still_blocks(
        self, _name: str, view_query: str, expected: str
    ) -> None:
        database = Database()
        database._add_views(
            TableNode(
                children={
                    "upstream_view": TableNode(
                        name="upstream_view",
                        table=SavedQuery(
                            id="upstream_view",
                            name="upstream_view",
                            query=view_query,
                            fields={
                                "team_id_": IntegerDatabaseField(name="team_id_"),
                                "has_views": IntegerDatabaseField(name="has_views"),
                            },
                        ),
                    )
                }
            )
        )

        result = self._check(
            "SELECT coalesce(team_id_, 0) AS new_team_id, has_views FROM upstream_view WHERE team_id_ < 100000",
            IncrementalConfig(incremental_key="new_team_id", unique_key=("new_team_id",)),
            database=database,
        )

        assert not result.eligible
        assert any(expected in blocker for blocker in result.blockers), result.blockers


DAILY_EVENT_TYPES = {"day": "DateTime64(6, 'UTC')", "event": "String", "c": "UInt64"}


class TestProposeIncrementalConfig(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "grouped_by_one_time_column",
                "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
                DAILY_EVENT_TYPES,
                DAY_EVENT_KEY,
            ),
            ("not_grouped", "SELECT uuid, timestamp FROM events", {"uuid": "UUID", "timestamp": "DateTime64(6)"}, None),
            (
                "two_time_columns",
                "SELECT toStartOfDay(timestamp) AS day, toStartOfHour(timestamp) AS hour, count() AS c "
                "FROM events GROUP BY day, hour",
                {"day": "DateTime", "hour": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "nullable_grouped_column",
                "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
                {**DAILY_EVENT_TYPES, "event": "Nullable(String)"},
                None,
            ),
            (
                "grouped_by_a_column_the_output_drops",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day, event",
                DAILY_EVENT_TYPES,
                None,
            ),
            ("column_types_unknown", GROUPED, {}, None),
            (
                "grouping_repeats_the_expression",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY toStartOfDay(timestamp)",
                {"day": "DateTime", "c": "UInt64"},
                DAY_KEY,
            ),
            (
                "key_from_a_nondeterministic_function",
                "SELECT today() AS day, event, count() AS c FROM events GROUP BY day, event",
                {**DAILY_EVENT_TYPES, "day": "Date"},
                None,
            ),
            (
                "moving_window_filter",
                f"{GROUPED.replace(' GROUP BY', ' WHERE timestamp >= now() - INTERVAL 7 DAY GROUP BY')}",
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "grouped_by_a_source_column_the_output_transforms",
                "SELECT toStartOfDay(timestamp) AS day, lower(e.event) AS event, count() AS c "
                "FROM events AS e GROUP BY day, e.event",
                DAILY_EVENT_TYPES,
                None,
            ),
            (
                "group_by_all_with_a_mixed_aggregate",
                "SELECT toStartOfDay(timestamp) AS day, concat(event, toString(count())) AS c FROM events GROUP BY ALL",
                {"day": "DateTime", "c": "String"},
                None,
            ),
            (
                "moving_window_from_a_clock_alias",
                GROUPED.replace(" GROUP BY", " WHERE timestamp >= current_date() - INTERVAL 7 DAY GROUP BY"),
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "moving_window_from_a_scalar_subquery",
                GROUPED.replace(
                    " GROUP BY", " WHERE timestamp >= (SELECT max(timestamp) FROM events) - INTERVAL 7 DAY GROUP BY"
                ),
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "moving_window_from_a_column_cte",
                "WITH (SELECT max(timestamp) FROM events) AS latest "
                + GROUPED.replace(" GROUP BY", " WHERE timestamp >= latest - INTERVAL 7 DAY GROUP BY"),
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "cohort_filter",
                GROUPED.replace(" GROUP BY", " WHERE person_id IN COHORT 1 GROUP BY"),
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "cohort_function_filter",
                GROUPED.replace(" GROUP BY", " WHERE person_id IN cohort(1) GROUP BY"),
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "date_key_that_wraps_at_the_year",
                "SELECT toDate(subtractYears(timestamp, toYear(timestamp) - 2000)) AS day, count() AS c "
                "FROM events GROUP BY day",
                {"day": "Date", "c": "UInt64"},
                None,
            ),
            (
                "date_key_that_wraps_inside_a_subquery",
                "SELECT day, count() AS c FROM (SELECT toDate(subtractYears(timestamp, toYear(timestamp) - 2000)) "
                "AS day FROM events) GROUP BY day",
                {"day": "Date", "c": "UInt64"},
                None,
            ),
            (
                "day_key_inside_a_cte_read_from_a_subquery",
                "WITH good AS (SELECT toStartOfDay(timestamp) AS ts FROM events GROUP BY ts) "
                "SELECT toStartOfDay(sub.ts) AS day, count() AS c FROM (SELECT ts FROM good) AS sub GROUP BY day",
                {"day": "DateTime", "c": "UInt64"},
                DAY_KEY,
            ),
            (
                "date_key_that_wraps_inside_a_cte_read_from_a_subquery",
                "WITH bad AS (SELECT toDate(subtractYears(timestamp, toYear(timestamp) - 2000)) AS ts FROM events "
                "GROUP BY ts) SELECT toStartOfDay(sub.ts) AS day, count() AS c FROM (SELECT ts FROM bad) AS sub "
                "GROUP BY day",
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "array_join_over_a_subquery",
                GROUPED.replace(" GROUP BY", " ARRAY JOIN (SELECT groupArray(event) FROM events) AS labels GROUP BY"),
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "union_branches_can_repeat_a_key",
                f"{GROUPED} UNION ALL {GROUPED}",
                {"day": "DateTime", "c": "UInt64"},
                None,
            ),
            (
                "nullable_grouped_column_behind_low_cardinality",
                "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
                {**DAILY_EVENT_TYPES, "event": "LowCardinality(Nullable(String))"},
                None,
            ),
            (
                "group_by_all_over_an_unnamed_expression",
                "SELECT toStartOfDay(timestamp) AS day, lower(event), count() AS c FROM events GROUP BY ALL",
                DAILY_EVENT_TYPES,
                None,
            ),
        ]
    )
    def test_proposes_a_config_only_when_the_keys_are_certain(
        self, _name: str, query: str, column_types: dict[str, str], expected: Optional[IncrementalConfig]
    ) -> None:
        assert propose_incremental_config(query, column_types) == expected

    @parameterized.expand(
        [
            (
                "grouped_by_a_plain_column",
                "SELECT toStartOfDay(timestamp) AS day, event, count() AS c FROM events GROUP BY day, event",
                DAILY_EVENT_TYPES,
                DAY_EVENT_KEY,
            ),
            (
                "grouped_by_an_array_column",
                "SELECT toStartOfDay(timestamp) AS day, splitByChar(',', event) AS labels, count() AS c "
                "FROM events GROUP BY day, labels",
                {"day": "DateTime", "labels": "Array(String)", "c": "UInt64"},
                None,
            ),
        ]
    )
    def test_proposals_against_the_resolved_schema(
        self, _name: str, query: str, column_types: dict[str, str], expected: Optional[IncrementalConfig]
    ) -> None:
        assert propose_incremental_config(query, column_types, database=Database()) == expected

    @parameterized.expand(
        [
            ("key_from_the_view_that_advances", "a", DAY_KEY),
            ("key_from_the_view_that_wraps", "b", None),
        ]
    )
    def test_a_joined_time_key_is_checked_in_the_view_it_comes_from(
        self, _name: str, key_view: str, expected: Optional[IncrementalConfig]
    ) -> None:
        database = Database()
        database._add_views(
            TableNode(
                children={
                    name: TableNode(
                        name=name,
                        table=SavedQuery(
                            id=name,
                            name=name,
                            query=f"SELECT {expression} AS ts FROM events GROUP BY ts",
                            fields={"ts": DateTimeDatabaseField(name="ts")},
                        ),
                    )
                    for name, expression in (
                        ("a", "toStartOfDay(timestamp)"),
                        ("b", "toDate(subtractYears(timestamp, toYear(timestamp) - 2000))"),
                    )
                }
            )
        )

        proposed = propose_incremental_config(
            f"SELECT toStartOfDay({key_view}.ts) AS day, count() AS c FROM a CROSS JOIN b GROUP BY day",
            {"day": "DateTime", "c": "UInt64"},
            database=database,
        )

        assert proposed == expected

    @parameterized.expand(
        [
            ("moving_window", "SELECT timestamp FROM events WHERE timestamp >= now() - INTERVAL 7 DAY"),
            ("cohort_filter", "SELECT timestamp FROM events WHERE person_id IN COHORT 1"),
        ]
    )
    def test_a_data_dependent_filter_inside_a_view_the_query_reads_blocks_the_proposal(
        self, _name: str, view_query: str
    ) -> None:
        database = Database()
        database._add_views(
            TableNode(
                children={
                    "last_week": TableNode(
                        name="last_week",
                        table=SavedQuery(
                            id="last_week",
                            name="last_week",
                            query=view_query,
                            fields={"timestamp": DateTimeDatabaseField(name="timestamp")},
                        ),
                    )
                }
            )
        )

        proposed = propose_incremental_config(
            GROUPED.replace("FROM events", "FROM last_week"), {"day": "DateTime", "c": "UInt64"}, database=database
        )

        assert proposed is None
