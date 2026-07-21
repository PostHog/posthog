import pytest

from posthog.hogql import ast
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLS3Table
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.logs import LogAttributesTable, LogsKafkaMetricsTable, LogsTable
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.errors import QueryError
from posthog.hogql.workload import MaterializedViewOnlyCollector, WorkloadCollector

from posthog.clickhouse.workload import Workload


class TestWorkloadCollector:
    """Test the WorkloadCollector visitor for detecting table workloads."""

    def test_logs_table_has_logs_workload(self):
        """LogsTable should have LOGS workload set."""
        logs_table = LogsTable()
        assert logs_table.workload == Workload.LOGS

    def test_log_attributes_table_has_logs_workload(self):
        """LogAttributesTable should have LOGS workload set."""
        log_attributes_table = LogAttributesTable()
        assert log_attributes_table.workload == Workload.LOGS

    def test_logs_kafka_metrics_table_has_logs_workload(self):
        """LogsKafkaMetricsTable should have LOGS workload set."""
        logs_kafka_metrics_table = LogsKafkaMetricsTable()
        assert logs_kafka_metrics_table.workload == Workload.LOGS

    def test_events_table_has_no_workload(self):
        """EventsTable should not have a workload set."""
        events_table = EventsTable()
        assert events_table.workload is None

    def test_collector_detects_logs_workload(self):
        """WorkloadCollector should detect LOGS workload from LogsTable."""
        collector = WorkloadCollector()

        # Create a TableType node with LogsTable
        table_type = ast.TableType(table=LogsTable())
        collector.visit(table_type)

        assert Workload.LOGS in collector.workloads
        assert collector.get_workload() == Workload.LOGS

    def test_collector_detects_no_workload_for_events(self):
        """WorkloadCollector should return default for EventsTable."""
        collector = WorkloadCollector()

        # Create a TableType node with EventsTable
        table_type = ast.TableType(table=EventsTable())
        collector.visit(table_type)

        assert len(collector.workloads) == 1
        assert collector.get_workload() == Workload.DEFAULT

    def test_collector_raises_error_for_multiple_workloads(self):
        """WorkloadCollector should raise error when multiple workloads detected."""
        collector = WorkloadCollector()

        # Add logs table
        logs_type = ast.TableType(table=LogsTable())
        collector.visit(logs_type)

        # Manually add a different workload to simulate cross-cluster query
        collector.workloads.add(Workload.ENDPOINTS)

        with pytest.raises(QueryError) as exc_info:
            collector.get_workload()

        assert "Cannot query tables from different clusters" in str(exc_info.value)

    def test_collector_handles_table_alias_type(self):
        """WorkloadCollector should detect workload through TableAliasType."""
        collector = WorkloadCollector()

        # Create a TableAliasType wrapping a TableType with LogsTable
        table_type = ast.TableType(table=LogsTable())
        alias_type = ast.TableAliasType(alias="l", table_type=table_type)
        collector.visit(alias_type)

        assert Workload.LOGS in collector.workloads
        assert collector.get_workload() == Workload.LOGS

    def test_collector_handles_virtual_table_type(self):
        """WorkloadCollector should detect workload through VirtualTableType."""
        collector = WorkloadCollector()

        # Create a VirtualTableType wrapping a TableType with LogsTable
        from posthog.hogql.database.models import VirtualTable

        table_type = ast.TableType(table=LogsTable())
        virtual_table = VirtualTable(fields={})
        virtual_type = ast.VirtualTableType(table_type=table_type, virtual_table=virtual_table, field="test_field")
        collector.visit(virtual_type)

        assert Workload.LOGS in collector.workloads
        assert collector.get_workload() == Workload.LOGS


class TestMaterializedViewOnlyCollector:
    """Branch logic for MaterializedViewOnlyCollector — routes only reads that touch nothing but
    materialized-view S3 tables to the endpoints cluster."""

    @staticmethod
    def _matview_table() -> HogQLS3Table:
        return HogQLS3Table(name="mv", url="s3://bucket/mv/*", format="Parquet", fields={}, is_materialized_view=True)

    @staticmethod
    def _warehouse_source_table() -> HogQLS3Table:
        # A raw synced warehouse-source table: same S3 machinery, but NOT a materialized view.
        return HogQLS3Table(name="stripe_charge", url="s3://bucket/stripe/*", format="Parquet", fields={})

    def test_matview_only_is_routable(self):
        collector = MaterializedViewOnlyCollector()
        collector.visit(ast.TableType(table=self._matview_table()))
        assert collector.is_materialized_view_only is True

    def test_matview_with_another_real_table_is_not_routable(self):
        collector = MaterializedViewOnlyCollector()
        collector.visit(ast.TableType(table=self._matview_table()))
        collector.visit(ast.TableType(table=EventsTable()))
        assert collector.is_materialized_view_only is False

    def test_raw_warehouse_source_table_is_not_routable(self):
        # Scope guard: unmarked S3 tables (warehouse sources) must not route — matviews only.
        collector = MaterializedViewOnlyCollector()
        collector.visit(ast.TableType(table=self._warehouse_source_table()))
        assert collector.is_materialized_view_only is False

    def test_standalone_function_table_does_not_disqualify(self):
        # numbers()/range() are pure compute with no cluster affinity — they don't block routing.
        collector = MaterializedViewOnlyCollector()
        collector.visit(ast.TableType(table=self._matview_table()))
        collector.visit(ast.TableType(table=NumbersTable()))
        assert collector.is_materialized_view_only is True

    def test_no_tables_is_not_routable(self):
        assert MaterializedViewOnlyCollector().is_materialized_view_only is False
