from datetime import UTC, datetime
from uuid import UUID, uuid4

from products.alerts.backend.logic.platform_alert_events import PlatformAlertEventRow, _deduplication_token

CONFIGURATION_ID = uuid4()
EVALUATION_KEY = "slot:2026-09-16T10:00:00+00:00|window:2026-09-16T09:59:00+00:00"


def _row(grouping_key: str, alert_id: UUID) -> PlatformAlertEventRow:
    return PlatformAlertEventRow(
        team_id=2,
        configuration_id=CONFIGURATION_ID,
        alert_id=alert_id,
        grouping_key=grouping_key,
        evaluation_key=EVALUATION_KEY,
        kind="firing",
        alert_name="API errors",
        previous_state="not_firing",
        state="firing",
        value=47.0,
        labels={},
        condition_snapshot={},
        source_config_snapshot={},
        query_duration_ms=None,
        error_message=None,
        consecutive_failures=0,
        muted_notification="",
        occurred_at=datetime(2026, 9, 16, 10, tzinfo=UTC),
    )


class TestDeduplicationToken:
    def test_batches_holding_different_groups_take_different_names(self) -> None:
        first = [_row("api", uuid4()), _row("web", uuid4())]
        second = [_row("api", uuid4()), _row("billing", uuid4())]

        # Same configuration and evaluation key, so a token blind to the group would name both
        # batches alike and ClickHouse would drop the second insert whole.
        assert _deduplication_token(2, first) != _deduplication_token(2, second)

    def test_the_same_batch_keeps_its_name_across_a_retry(self) -> None:
        rows = [_row("api", uuid4()), _row("web", uuid4())]

        assert _deduplication_token(2, rows) == _deduplication_token(2, list(reversed(rows)))
