import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.logs import LogAttributesTable, LogsKafkaMetricsTable, LogsTable
from posthog.hogql.database.schema.spans import TraceSpansTable
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.workload import WorkloadCollector

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import LogsClusterSignal, Workload


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

    @parameterized.expand(
        [
            ("one_signal", [LogsTable(), LogAttributesTable()], LogsClusterSignal.LOGS),
            ("two_signals", [LogsTable(), TraceSpansTable()], None),
            ("logs_table_without_signal", [LogsTable(), LogsTable(logs_cluster_signal=None)], None),
        ]
    )
    def test_collector_finds_one_logs_cluster_signal(self, _name, tables, expected):
        collector = WorkloadCollector()
        for table in tables:
            collector.visit(ast.TableType(table=table))

        assert collector.get_logs_cluster_signal() == expected


class TestExecuteHogQLQueryWorkload(BaseTest):
    @parameterized.expand(
        [
            ("spans_offline", "SELECT 1 FROM posthog.trace_spans", Workload.OFFLINE, Workload.LOGS),
            ("spans_online", "SELECT 1 FROM posthog.trace_spans", Workload.ONLINE, Workload.LOGS),
            ("logs_offline", "SELECT 1 FROM logs", Workload.OFFLINE, Workload.LOGS),
            ("events_offline", "SELECT 1 FROM events", Workload.OFFLINE, Workload.OFFLINE),
        ]
    )
    def test_table_cluster_wins_over_priority_workload(
        self, _name: str, query: str, requested: Workload, expected: Workload
    ) -> None:
        with patch("posthog.hogql.query.sync_execute", return_value=([], [])) as sync_execute:
            execute_hogql_query(query=parse_select(query), team=self.team, workload=requested)

        assert sync_execute.call_args.kwargs["workload"] == expected

    @parameterized.expand(
        [
            ("logs", "SELECT 1 FROM logs", ClickHouseUser.DEFAULT, ClickHouseUser.LOGS),
            ("log_attributes", "SELECT 1 FROM log_attributes", ClickHouseUser.DEFAULT, ClickHouseUser.LOGS),
            ("metric_samples", "SELECT 1 FROM posthog.metric_samples", ClickHouseUser.DEFAULT, ClickHouseUser.METRICS),
            ("spans", "SELECT 1 FROM posthog.trace_spans", ClickHouseUser.DEFAULT, ClickHouseUser.TRACES),
            ("app_user_on_metrics", "SELECT 1 FROM posthog.metric_samples", ClickHouseUser.APP, ClickHouseUser.METRICS),
            (
                "logs_and_spans",
                "SELECT 1 FROM logs WHERE trace_id IN (SELECT trace_id FROM posthog.trace_spans)",
                ClickHouseUser.DEFAULT,
                ClickHouseUser.DEFAULT,
            ),
            (
                "named_logs_user",
                "SELECT 1 FROM logs",
                ClickHouseUser.ALERTS_PLATFORM_LOGS,
                ClickHouseUser.ALERTS_PLATFORM_LOGS,
            ),
            ("events", "SELECT 1 FROM events", ClickHouseUser.APP, ClickHouseUser.APP),
        ]
    )
    def test_logs_cluster_tables_pick_the_user_of_their_signal(
        self, _name: str, query: str, requested: ClickHouseUser, expected: ClickHouseUser
    ) -> None:
        with patch("posthog.hogql.query.sync_execute", return_value=([], [])) as sync_execute:
            execute_hogql_query(query=parse_select(query), team=self.team, workload=Workload.ONLINE, ch_user=requested)

        assert sync_execute.call_args.kwargs["ch_user"] == expected
