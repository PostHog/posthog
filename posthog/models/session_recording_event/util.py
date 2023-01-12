from typing import Union

from django.utils import timezone

from posthog.client import sync_execute


def get_recording_count_for_team_and_period(
    team_id: Union[str, int], begin: timezone.datetime, end: timezone.datetime
) -> int:
    result = sync_execute(
        """
        SELECT count(distinct session_id) as count
        FROM session_recording_events
        WHERE team_id = %(team_id)s
        AND timestamp between %(begin)s AND %(end)s
    """,
        {"team_id": str(team_id), "begin": begin, "end": end},
    )[0][0]
    return result


def get_recording_count_month_to_date() -> int:
    result = sync_execute(
        """
        -- count of recordings month to date
        SELECT count(distinct session_id) as freq
        FROM session_recording_events
        WHERE toStartOfMonth(timestamp) = toStartOfMonth(now());
    """
    )[0][0]
    return result


def get_recording_events_count_month_to_date() -> int:
    result = sync_execute(
        """
        -- count of recordings events month to date
        SELECT count(1) freq
        FROM session_recording_events
        WHERE toStartOfMonth(timestamp) = toStartOfMonth(now());
    """
    )[0][0]
    return result
