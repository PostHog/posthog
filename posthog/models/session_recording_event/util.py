from posthog.client import sync_execute


def get_recording_count_month_to_date() -> int:
    result = sync_execute(
        """
        SELECT count(distinct session_id) as freq
        FROM session_replay_events
        WHERE toStartOfMonth(min_first_timestamp) = toStartOfMonth(now())
    """
    )[0][0]
    return result


def get_recording_events_count_month_to_date() -> int:
    result = sync_execute(
        """
        SELECT count() freq
        FROM session_replay_events
        WHERE toStartOfMonth(min_first_timestamp) = toStartOfMonth(now())
    """
    )[0][0]
    return result
