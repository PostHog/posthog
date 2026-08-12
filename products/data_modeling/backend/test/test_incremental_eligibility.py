from posthog.test.base import BaseTest

from parameterized import parameterized

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
