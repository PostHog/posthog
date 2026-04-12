"""Tests for state_diff convergence — verifying idempotent apply (second run = 0 diffs)."""

from unittest.mock import patch

from posthog.clickhouse.migration_tools.desired_state import ColumnDef, DesiredState, DesiredTable
from posthog.clickhouse.migration_tools.schema_introspect import ColumnSchema, TableSchema
from posthog.clickhouse.migration_tools.state_diff import (
    _is_kafka_virtual_column,
    _normalize_default,
    _normalize_interval_funcs,
    diff_state,
)

# -- Fix 1: Interval normalization --


class TestNormalizeIntervalFuncs:
    def test_toIntervalDay(self):
        assert _normalize_interval_funcs("today() + toIntervalDay(7)") == "today() + INTERVAL 7 DAY"

    def test_toIntervalHour(self):
        assert _normalize_interval_funcs("now() + toIntervalHour(24)") == "now() + INTERVAL 24 HOUR"

    def test_toIntervalMinute(self):
        assert _normalize_interval_funcs("toIntervalMinute(30)") == "INTERVAL 30 MINUTE"

    def test_toIntervalSecond(self):
        assert _normalize_interval_funcs("toIntervalSecond(60)") == "INTERVAL 60 SECOND"

    def test_toIntervalWeek(self):
        assert _normalize_interval_funcs("toIntervalWeek(2)") == "INTERVAL 2 WEEK"

    def test_toIntervalMonth(self):
        assert _normalize_interval_funcs("toIntervalMonth(1)") == "INTERVAL 1 MONTH"

    def test_toIntervalYear(self):
        assert _normalize_interval_funcs("toIntervalYear(1)") == "INTERVAL 1 YEAR"

    def test_no_change_for_interval_literal(self):
        s = "INTERVAL 7 DAY"
        assert _normalize_interval_funcs(s) == s

    def test_whitespace_in_parens(self):
        assert _normalize_interval_funcs("toIntervalDay(  7  )") == "INTERVAL 7 DAY"

    def test_multiple_intervals(self):
        s = "toIntervalDay(1) + toIntervalHour(2)"
        assert _normalize_interval_funcs(s) == "INTERVAL 1 DAY + INTERVAL 2 HOUR"


class TestNormalizeDefault:
    def test_interval_forms_equivalent(self):
        a = "DEFAULT today() + toIntervalDay(7)"
        b = "DEFAULT today() + INTERVAL 7 DAY"
        assert _normalize_default(a) == _normalize_default(b)

    def test_case_insensitive(self):
        assert _normalize_default("DEFAULT NOW()") == _normalize_default("DEFAULT now()")

    def test_whitespace_collapse(self):
        assert _normalize_default("DEFAULT  now(  )") == _normalize_default("DEFAULT now( )")

    def test_empty_string(self):
        assert _normalize_default("") == ""

    def test_preserves_string_literals(self):
        a = "DEFAULT 'UTC'"
        assert _normalize_default(a) == "default 'utc'"


# -- Fix 2: Kafka virtual columns --


class TestKafkaVirtualColumns:
    def test_known_virtual_columns(self):
        for col in ("_topic", "_key", "_offset", "_partition", "_timestamp", "_headers"):
            assert _is_kafka_virtual_column(col), f"{col} should be virtual"

    def test_headers_dot_prefix(self):
        assert _is_kafka_virtual_column("_headers.name")
        assert _is_kafka_virtual_column("_headers.value")

    def test_regular_column_not_virtual(self):
        assert not _is_kafka_virtual_column("team_id")
        assert not _is_kafka_virtual_column("event")
        assert not _is_kafka_virtual_column("timestamp")


# -- Integration: diff_state convergence --


def _make_desired(tables: dict[str, DesiredTable]) -> DesiredState:
    return DesiredState(ecosystem="test", cluster="test_cluster", tables=tables)


def _col(name: str, type: str, default_kind: str = "", default_expression: str = "") -> ColumnDef:
    return ColumnDef(name=name, type=type, default_kind=default_kind, default_expression=default_expression)


def _live_col(name: str, type: str, default_kind: str = "", default_expression: str = "") -> ColumnSchema:
    return ColumnSchema(name=name, type=type, default_kind=default_kind, default_expression=default_expression)


# Patch _resolve_physical_cluster and _resolve_setting to avoid Django settings dependency
_PATCH_RESOLVE = patch(
    "posthog.clickhouse.migration_tools.state_diff._resolve_physical_cluster",
    return_value="test_cluster",
)
_PATCH_SETTING = patch(
    "posthog.clickhouse.migration_tools.state_diff._resolve_setting",
    side_effect=lambda k: k,
)


class TestDiffConvergenceIntervalDefault:
    """Fix 1: toIntervalDay(7) in YAML should match INTERVAL 7 DAY from system.columns."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_spurious_alter_for_interval_default(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "test_table": DesiredTable(
                    name="test_table",
                    engine="ReplacingMergeTree",
                    columns=[
                        _col("id", "UInt64"),
                        _col(
                            "expires", "Date", default_kind="DEFAULT", default_expression="today() + toIntervalDay(7)"
                        ),
                    ],
                    on_nodes=["all"],
                    order_by=["id"],
                ),
            }
        )
        current = {
            "test_table": TableSchema(
                name="test_table",
                engine="ReplacingMergeTree",
                columns=[
                    _live_col("id", "UInt64"),
                    _live_col("expires", "Date", default_kind="DEFAULT", default_expression="today() + INTERVAL 7 DAY"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


class TestDiffConvergenceKafkaVirtualColumns:
    """Fix 2: Kafka virtual columns should not trigger recreate."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_recreate_when_only_virtual_columns_differ(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[
                        _col("event", "String"),
                        _col("timestamp", "DateTime"),
                    ],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
            }
        )
        # Live schema includes virtual columns injected by CH
        current = {
            "kafka_events": TableSchema(
                name="kafka_events",
                engine="Kafka",
                columns=[
                    _live_col("event", "String"),
                    _live_col("timestamp", "DateTime"),
                    _live_col("_topic", "LowCardinality(String)"),
                    _live_col("_key", "String"),
                    _live_col("_offset", "UInt64"),
                    _live_col("_partition", "UInt64"),
                    _live_col("_timestamp", "Nullable(DateTime)"),
                    _live_col("_headers", "Map(String, String)"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


class TestDiffConvergenceDistributedEmptyColumns:
    """Fix 4: Distributed tables with columns: [] should not generate column diffs."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_drop_columns_for_empty_desired(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "events_dist": DesiredTable(
                    name="events_dist",
                    engine="Distributed",
                    columns=[],  # inherit from source
                    on_nodes=["all"],
                    source="sharded_events",
                ),
            }
        )
        # Live schema has real columns (inherited from source at creation time)
        current = {
            "events_dist": TableSchema(
                name="events_dist",
                engine="Distributed",
                columns=[
                    _live_col("uuid", "UUID"),
                    _live_col("event", "String"),
                    _live_col("timestamp", "DateTime"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        # Should not produce DROP COLUMN diffs
        drop_diffs = [d for d in diffs if "drop_column" in d.action.lower() or "Drop column" in d.detail]
        assert len(drop_diffs) == 0, f"Expected no column drops but got: {[d.detail for d in drop_diffs]}"


class TestDiffConvergenceKafkaMVStability:
    """Fix 3: Kafka table not being recreated means its MV stays stable too."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_kafka_and_mv_stable_on_second_apply(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[
                        _col("event", "String"),
                    ],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
                "kafka_events_mv": DesiredTable(
                    name="kafka_events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event FROM posthog.kafka_events",
                ),
            }
        )
        current = {
            "kafka_events": TableSchema(
                name="kafka_events",
                engine="Kafka",
                columns=[
                    _live_col("event", "String"),
                    _live_col("_topic", "LowCardinality(String)"),
                    _live_col("_offset", "UInt64"),
                ],
            ),
            "kafka_events_mv": TableSchema(
                name="kafka_events_mv",
                engine="MaterializedView",
                as_select="SELECT event FROM posthog.kafka_events",
                columns=[
                    _live_col("event", "String"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"
