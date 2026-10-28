from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.execute import default_settings, sync_execute
from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL, LOG_ENTRIES_DATA_TABLE, LOG_ENTRIES_TABLE
from posthog.settings import CLICKHOUSE_AUX_CLUSTER, CLICKHOUSE_DATABASE

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.destination_debug_logs import (
    DebugLogScope,
    _log_entries_reads_aux,
    count_debug_logs,
    delete_debug_logs,
    find_destination_functions,
)

MODULE = "products.cdp.backend.services.destination_debug_logs"
CUTOFF = datetime(2026, 9, 18, 10, 0, 0, tzinfo=UTC)
BEFORE = CUTOFF - timedelta(days=1)
AFTER = CUTOFF + timedelta(hours=1)


class TestDestinationDebugLogs(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.segment = HogFunction.objects.create(
            team=self.team, name="segment", type="destination", template_id="segment-actions-example", hog=""
        )
        self.deleted_segment = HogFunction.objects.create(
            team=self.team, name="old", type="destination", template_id="segment-example", hog="", deleted=True
        )
        self.hog = HogFunction.objects.create(
            team=self.team, name="hog", type="destination", template_id="template-webhook", hog=""
        )

    def _insert(
        self, function: HogFunction, level: str, message: str, timestamp: datetime, table: str = LOG_ENTRIES_TABLE
    ) -> None:
        # The table is a ReplacingMergeTree keyed on the timestamp, so every row needs its own.
        sync_execute(
            INSERT_LOG_ENTRY_SQL.replace(f"INSERT INTO {LOG_ENTRIES_TABLE} ", f"INSERT INTO {table} "),
            {
                "team_id": function.team_id,
                "log_source": "hog_function",
                "log_source_id": str(function.id),
                "instance_id": "inv-1",
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "level": level,
                "message": message,
            },
        )

    def _remaining(self, table: str = LOG_ENTRIES_TABLE) -> set[tuple[str, str]]:
        rows = sync_execute(
            f"SELECT log_source_id, message FROM {table} WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
        )
        return {(function_id, message) for function_id, message in rows}

    def test_deletes_only_the_dumped_lines_of_destination_functions_before_the_cutoff(self) -> None:
        doomed = [
            (self.segment, 'config, {"apiKey":"key-1234567890"}'),
            (self.segment, 'options, {"json":{"apiKey":"key-1234567890"}}'),
            (self.segment, 'headers, {"Api-Key":"key-1234567890"}'),
            (self.segment, 'requestExtension, {"headers":{"Api-Key":"key-1234567890"}}'),
            (self.segment, 'fetchOptions, {"body":"{\\"apiKey\\":\\"key-1234567890\\"}"}'),
            (self.deleted_segment, 'config, {"apiKey":"key-0987654321"}'),
        ]
        kept = [
            (self.segment, "debug", "endpoint, https://api.example.com/track", BEFORE),
            (self.segment, "info", "Function completed in 12ms.", BEFORE),
            (self.segment, "error", 'config, {"apiKey":"key-1234567890"}', BEFORE),
            (self.segment, "debug", 'config, {"apiKey":"key-1234567890"}', AFTER),
            (self.hog, "debug", 'config, {"apiKey":"key-1234567890"}', BEFORE),
        ]
        for i, (function, message) in enumerate(doomed):
            self._insert(function, "debug", message, BEFORE + timedelta(seconds=i))
        for i, (function, level, message, timestamp) in enumerate(kept, start=len(doomed)):
            self._insert(function, level, message, timestamp + timedelta(seconds=i))

        scope = DebugLogScope(before=CUTOFF, team_id=self.team.pk)
        functions = find_destination_functions(scope)
        assert set(functions) == {(self.team.pk, str(self.segment.id)), (self.team.pk, str(self.deleted_segment.id))}

        count = count_debug_logs(scope, functions)
        assert (count.lines, count.functions, count.teams) == (len(doomed), 2, 1)

        delete_debug_logs(scope, functions, wait=True)

        assert self._remaining() == {(str(function.id), message) for function, _, message, _ in kept}
        assert count_debug_logs(scope, functions).lines == 0

    def test_deletes_from_aux_data_table_on_an_aux_host(self) -> None:
        scope = DebugLogScope(before=CUTOFF, team_id=self.team.pk)
        functions = [(self.team.pk, str(self.segment.id))]
        cluster = MagicMock()
        client = MagicMock()
        cluster.any_host_by_role.side_effect = lambda fn, role: MagicMock(result=lambda: fn(client))

        with (
            patch(f"{MODULE}._log_entries_reads_aux", return_value=True),
            patch(f"{MODULE}.collapses_to_all_nodes", return_value=False),
            patch(f"{MODULE}.get_migrations_cluster", return_value=cluster),
        ):
            delete_debug_logs(scope, functions)

        assert cluster.any_host_by_role.call_args.args[1] == NodeRole.AUX
        sql, args = client.execute.call_args.args
        assert sql.startswith(f"DELETE FROM {LOG_ENTRIES_DATA_TABLE} WHERE")
        assert args["functions"] == functions
        settings = client.execute.call_args.kwargs["settings"]
        assert settings["lightweight_deletes_sync"] == 0
        assert settings["max_query_size"] == default_settings()["max_query_size"]

    def test_deletes_from_aux_data_table_on_the_local_node_when_topology_collapses(self) -> None:
        doomed = (self.segment, 'config, {"apiKey":"key-1234567890"}')
        kept = (self.segment, "endpoint, https://api.example.com/track")
        for i, (function, message) in enumerate([doomed, kept]):
            self._insert(function, "debug", message, BEFORE + timedelta(seconds=i), table=LOG_ENTRIES_DATA_TABLE)

        scope = DebugLogScope(before=CUTOFF, team_id=self.team.pk)
        with (
            patch(f"{MODULE}._log_entries_reads_aux", return_value=True),
            patch(f"{MODULE}.collapses_to_all_nodes", return_value=True),
        ):
            delete_debug_logs(scope, [(self.team.pk, str(self.segment.id))], wait=True)

        assert self._remaining(table=LOG_ENTRIES_DATA_TABLE) == {(str(kept[0].id), kept[1])}

    @parameterized.expand(
        [
            ("local MergeTree", "ReplacingMergeTree(_timestamp) ORDER BY team_id", False),
            (
                "aux reader",
                f"Distributed('{CLICKHOUSE_AUX_CLUSTER}', '{CLICKHOUSE_DATABASE}', 'log_entries_data')",
                True,
            ),
        ]
    )
    def test_detects_whether_log_entries_reads_aux(self, _name: str, engine_full: str, expected: bool) -> None:
        with patch(f"{MODULE}.sync_execute", return_value=[(engine_full,)]):
            assert _log_entries_reads_aux() is expected

    def test_refuses_when_log_entries_reads_another_table(self) -> None:
        engine_full = f"Distributed('posthog', '{CLICKHOUSE_DATABASE}', 'sharded_log_entries', rand())"
        with patch(f"{MODULE}.sync_execute", return_value=[(engine_full,)]), pytest.raises(RuntimeError):
            _log_entries_reads_aux()
