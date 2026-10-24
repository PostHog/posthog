import re
import uuid

from unittest.mock import MagicMock, patch

from posthog.temporal.ai_observability.generated_event_usage import create_generated_ai_event


@patch("posthog.temporal.ai_observability.generated_event_usage.report_usage")
@patch("posthog.temporal.ai_observability.generated_event_usage.create_event")
def test_reports_one_ai_event_record_for_each_generated_event(create_event: MagicMock, report_usage: MagicMock) -> None:
    team = MagicMock(id=42)
    first_uuid, second_uuid = uuid.uuid4(), uuid.uuid4()
    for event_uuid in (first_uuid, second_uuid):
        create_generated_ai_event(
            event_uuid=event_uuid,
            event="$ai_trace_summary",
            team=team,
            distinct_id="trace_summary_42",
            properties={"$ai_trace_id": "trace-1"},
        )

    records = [call.args[0][0] for call in report_usage.call_args_list]
    assert [(r.team_id, r.usage_key, r.unit, r.quantity) for r in records] == [(42, "ai_events", "events", 1)] * 2
    day = create_event.call_args_list[0].kwargs["timestamp"].date().isoformat()
    assert re.fullmatch(rf"{day}:[0-9a-f]{{32}}", records[0].record_id)
    assert records[0].record_id != records[1].record_id
