import datetime as dt
from typing import Any
from posthog.clickhouse.client import sync_execute


def get_sampled_session_ids(
    started_after: dt.datetime,
    started_before: dt.datetime,
    sample_size: int,
) -> list[tuple[str, int]]:  # [(session_id, team_id), ...]
    """Get a random sample of session IDs from the specified time range."""
    query = """
        SELECT DISTINCT session_id, team_id
        FROM session_replay_events
        WHERE min_first_timestamp >= %(started_after)s
        AND max_last_timestamp <= %(started_before)s
        ORDER BY rand()  -- Random sampling
        LIMIT %(sample_size)s
    """

    results = sync_execute(
        query,
        {
            "started_after": started_after.strftime("%Y-%m-%d %H:%M:%S"),
            "started_before": started_before.strftime("%Y-%m-%d %H:%M:%S"),
            "sample_size": sample_size,
        },
    )
    return [(str(row[0]), int(row[1])) for row in results]


def get_session_metadata(team_id: int, session_id: str, table_name: str) -> dict[str, Any]:
    """Get metadata counts for a specific session from the specified table."""
    query = """
        SELECT
            session_id,
            team_id,
            any(distinct_id) as distinct_id,
            min(min_first_timestamp) as min_first_timestamp_agg,
            max(max_last_timestamp) as max_last_timestamp_agg,
            argMinMerge(first_url) as first_url,
            groupUniqArrayArray(all_urls) as all_urls,
            sum(click_count) as click_count,
            sum(keypress_count) as keypress_count,
            sum(mouse_activity_count) as mouse_activity_count,
            sum(active_milliseconds) as active_milliseconds,
            sum(console_log_count) as console_log_count,
            sum(console_warn_count) as console_warn_count,
            sum(console_error_count) as console_error_count,
            sum(event_count) as event_count,
            argMinMerge(snapshot_source) as snapshot_source,
            argMinMerge(snapshot_library) as snapshot_library
        FROM {table}
        WHERE team_id = %(team_id)s
        AND session_id = %(session_id)s
        GROUP BY session_id, team_id
        LIMIT 1
    """
    result = sync_execute(
        query.format(table=table_name),
        {
            "team_id": team_id,
            "session_id": session_id,
        },
    )
    if not result:
        return {
            "click_count": 0,
            "mouse_activity_count": 0,
            "keypress_count": 0,
            "event_count": 0,
            "console_log_count": 0,
            "console_warn_count": 0,
            "console_error_count": 0,
            "first_url": None,
            "all_urls": [],
            "snapshot_source": None,
            "snapshot_library": None,
            "active_milliseconds": 0,
        }

    row = result[0]
    return {
        "click_count": row[7],  # click_count index
        "keypress_count": row[8],  # keypress_count index
        "mouse_activity_count": row[9],  # mouse_activity_count index
        "console_log_count": row[11],  # console_log_count index
        "console_warn_count": row[12],  # console_warn_count index
        "console_error_count": row[13],  # console_error_count index
        "event_count": row[14],  # event_count index
        "first_url": row[5],  # first_url index
        "all_urls": row[6],  # all_urls index
        "snapshot_source": row[15],  # snapshot_source index
        "snapshot_library": row[16],  # snapshot_library index
        "active_milliseconds": row[10],  # active_milliseconds index
    }
