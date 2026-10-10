from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.destination_debug_logs import (
    DebugLogScope,
    count_debug_logs,
    delete_debug_logs,
    find_destination_functions,
)

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

    def _insert(self, function: HogFunction, level: str, message: str, timestamp: datetime) -> None:
        # The table is a ReplacingMergeTree keyed on the timestamp, so every row needs its own.
        sync_execute(
            INSERT_LOG_ENTRY_SQL,
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

    def _remaining(self) -> set[tuple[str, str]]:
        rows = sync_execute(
            "SELECT log_source_id, message FROM log_entries WHERE team_id = %(team_id)s", {"team_id": self.team.pk}
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
        for i, (function, level, message, timestamp) in enumerate(kept):
            self._insert(function, level, message, timestamp + timedelta(seconds=i))

        scope = DebugLogScope(before=CUTOFF, team_id=self.team.pk)
        functions = find_destination_functions(scope)
        assert set(functions) == {(self.team.pk, str(self.segment.id)), (self.team.pk, str(self.deleted_segment.id))}

        count = count_debug_logs(scope, functions)
        assert (count.lines, count.functions, count.teams) == (len(doomed), 2, 1)

        delete_debug_logs(scope, functions, wait=True)

        assert self._remaining() == {(str(function.id), message) for function, _, message, _ in kept}
        assert count_debug_logs(scope, functions).lines == 0
