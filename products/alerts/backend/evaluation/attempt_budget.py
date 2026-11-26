from datetime import UTC, datetime, timedelta

from temporalio import activity


def attempt_outlasts(seconds: float) -> bool:
    """Whether the Temporal attempt running this check is live and has `seconds` of its budget left.

    An attempt that timed out or was cancelled keeps its thread, and the failed-check cleanup has
    already stopped its queries, so a query it started after that would hold a ClickHouse slot that
    nothing frees. Outside an activity there is no budget to outlast.
    """
    if not activity.in_activity():
        return True
    if activity.is_cancelled():
        return False
    info = activity.info()
    # The attempt starts after it is scheduled, so its scheduled time gives a deadline no later than
    # the real one. Schedule-to-close counts from the first attempt, so it can end a retry sooner.
    deadlines = []
    if info.start_to_close_timeout is not None:
        deadlines.append(info.current_attempt_scheduled_time + info.start_to_close_timeout)
    if info.schedule_to_close_timeout is not None:
        deadlines.append(info.scheduled_time + info.schedule_to_close_timeout)
    return not deadlines or datetime.now(UTC) + timedelta(seconds=seconds) < min(deadlines)
