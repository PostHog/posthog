import dataclasses

from posthog.clickhouse.client import sync_execute


@dataclasses.dataclass(frozen=True)
class RecordingsSystemStatus:
    count: int
    events: str
    size: int


def get_recording_status_month_to_date() -> RecordingsSystemStatus:
    result = sync_execute(
        """
        SELECT count(distinct session_id), sum(event_count), sum(message_count), formatReadableSize(sum(size))
        FROM session_replay_events
        WHERE toStartOfMonth(min_first_timestamp) = toStartOfMonth(now())
    """
    )[0]
    return RecordingsSystemStatus(
        count=result[0],
        events=f"{result[1]:,} rrweb events in {result[2]:,} messages",
        size=result[3],
    )
