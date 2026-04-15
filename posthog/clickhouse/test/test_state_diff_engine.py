"""Tests for diff_state convergence — verifying idempotent apply (second run = 0 diffs)."""

from unittest.mock import patch

from posthog.clickhouse.migration_tools.desired_state import ColumnDef, DesiredState, DesiredTable
from posthog.clickhouse.migration_tools.schema_introspect import ColumnSchema, TableSchema
from posthog.clickhouse.migration_tools.state_diff import _generate_create_sql, diff_state


def _make_desired(tables: dict[str, DesiredTable]) -> DesiredState:
    return DesiredState(ecosystem="test", cluster="test_cluster", tables=tables)


def _col(name: str, type: str, default_kind: str = "", default_expression: str = "") -> ColumnDef:
    return ColumnDef(name=name, type=type, default_kind=default_kind, default_expression=default_expression)


def _live_col(name: str, type: str, default_kind: str = "", default_expression: str = "") -> ColumnSchema:
    return ColumnSchema(name=name, type=type, default_kind=default_kind, default_expression=default_expression)


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
                    columns=[],
                    on_nodes=["all"],
                    source="sharded_events",
                ),
            }
        )
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
        drop_diffs = [d for d in diffs if "drop_column" in d.action.lower() or "Drop column" in d.detail]
        assert len(drop_diffs) == 0, f"Expected no column drops but got: {[d.detail for d in drop_diffs]}"


class TestDiffConvergenceKafkaMVStability:
    """Fix 3: Kafka table not recreated means its MV stays stable too."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_kafka_and_mv_stable_on_second_apply(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[_col("event", "String")],
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
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


class TestDiffConvergenceEnum8:
    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_alter_for_enum8_vs_enum(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "test_table": DesiredTable(
                    name="test_table",
                    engine="ReplacingMergeTree",
                    columns=[
                        _col("id", "UInt64"),
                        _col("status", "Enum('active', 'deleted')"),
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
                    _live_col("status", "Enum8('active' = 1, 'deleted' = 2)"),
                ],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


class TestDiffConvergenceMvSelect:
    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_recreate_when_only_db_prefix_differs(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "events_mv": DesiredTable(
                    name="events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event FROM kafka_events",
                ),
            }
        )
        current = {
            "events_mv": TableSchema(
                name="events_mv",
                engine="MaterializedView",
                as_select="SELECT event FROM posthog_test.kafka_events",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog_test", cluster="test_cluster")
        assert len(diffs) == 0, f"Expected 0 diffs but got: {[d.detail for d in diffs]}"


class TestKafkaMVCascadePrevention:
    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_kafka_recreated_after_mv_recreate(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[_col("event", "String")],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
                "sharded_events": DesiredTable(
                    name="sharded_events",
                    engine="ReplacingMergeTree",
                    columns=[_col("event", "String")],
                    on_nodes=["all"],
                    order_by=["event"],
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
                columns=[_live_col("event", "String")],
            ),
            "sharded_events": TableSchema(
                name="sharded_events",
                engine="ReplacingMergeTree",
                columns=[_live_col("event", "String")],
            ),
            "kafka_events_mv": TableSchema(
                name="kafka_events_mv",
                engine="MaterializedView",
                engine_full="MaterializedView TO posthog.old_target",
                as_select="SELECT event FROM posthog.kafka_events",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        mv_recreates = [d for d in diffs if d.action == "recreate_mv"]
        assert len(mv_recreates) == 1, f"Expected 1 MV recreate but got: {[d.detail for d in mv_recreates]}"
        kafka_creates = [d for d in diffs if d.action == "create" and d.table == "kafka_events"]
        assert len(kafka_creates) == 1, f"Expected Kafka re-create but got: {[d.detail for d in kafka_creates]}"
        assert "cascade" in kafka_creates[0].detail.lower()


class TestDistributedSourceWithDbPrefix:
    """P1-C: Distributed(..., '<db>', '<table>', ...) must split source on '.'."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_system_processes_split_into_db_and_table(self, _mock_setting, _mock_cluster):
        table = DesiredTable(
            name="distributed_system_processes",
            engine="Distributed",
            columns=[],
            on_nodes=["all"],
            source="system.processes",
        )
        sql = _generate_create_sql(table, "posthog_test", "test_cluster")

        assert "'system', 'processes'" in sql, f"Expected 'system', 'processes' in: {sql}"
        assert "'posthog_test', 'system.processes'" not in sql
        assert "AS system.processes" in sql

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_undotted_source_uses_current_database(self, _mock_setting, _mock_cluster):
        table = DesiredTable(
            name="events_dist",
            engine="Distributed",
            columns=[_col("uuid", "UUID")],
            on_nodes=["all"],
            source="sharded_events",
        )
        sql = _generate_create_sql(table, "posthog", "test_cluster")

        assert "'posthog', 'sharded_events'" in sql


class TestKafkaCascadeOnSelectChange:
    """P1-B: When an MV's SELECT changes, cascade fix re-creates the Kafka source."""

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_kafka_recreated_on_mv_select_change(self, _mock_setting, _mock_cluster):
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[_col("event", "String")],
                    on_nodes=["all"],
                    settings={"kafka_broker_list": "localhost:9092", "kafka_topic_list": "events"},
                ),
                "kafka_events_mv": DesiredTable(
                    name="kafka_events_mv",
                    engine="MaterializedView",
                    columns=[],
                    on_nodes=["all"],
                    target="sharded_events",
                    select="SELECT event, toUnixTimestamp(timestamp) AS ts FROM posthog.kafka_events",
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
                ],
            ),
            "kafka_events_mv": TableSchema(
                name="kafka_events_mv",
                engine="MaterializedView",
                as_select="SELECT event FROM posthog.kafka_events",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")

        mv_drops = [d for d in diffs if d.action == "drop" and d.table == "kafka_events_mv"]
        mv_creates = [d for d in diffs if d.action == "create" and d.table == "kafka_events_mv"]
        assert len(mv_drops) == 1, f"Expected MV drop; got {[d.detail for d in diffs]}"
        assert len(mv_creates) == 1, f"Expected MV create; got {[d.detail for d in diffs]}"

        kafka_creates = [d for d in diffs if d.action == "create" and d.table == "kafka_events"]
        assert len(kafka_creates) == 1, (
            f"Expected Kafka source to be re-added after MV recreate; got {[d.detail for d in diffs]}"
        )
        assert "cascade-dropped" in kafka_creates[0].detail.lower()

    @_PATCH_RESOLVE
    @_PATCH_SETTING
    def test_no_cascade_when_mv_stable(self, _mock_setting, _mock_cluster):
        """Regression: Kafka is not re-added when the MV isn't being recreated."""
        desired = _make_desired(
            {
                "kafka_events": DesiredTable(
                    name="kafka_events",
                    engine="Kafka",
                    columns=[_col("event", "String")],
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
                ],
            ),
            "kafka_events_mv": TableSchema(
                name="kafka_events_mv",
                engine="MaterializedView",
                as_select="SELECT event FROM posthog.kafka_events",
                columns=[_live_col("event", "String")],
            ),
        }
        diffs = diff_state(desired, current, database="posthog", cluster="test_cluster")
        kafka_creates = [d for d in diffs if d.action == "create" and d.table == "kafka_events"]
        assert len(kafka_creates) == 0, f"Unexpected Kafka recreate: {[d.detail for d in diffs]}"
