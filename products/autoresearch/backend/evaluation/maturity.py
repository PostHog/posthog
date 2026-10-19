"""When a prediction date's outcome window has closed and its last outcome events have landed."""

from datetime import UTC, date, datetime, timedelta

# An outcome event timestamped just before the window closes can still be in the ingestion
# queue when the window closes. Maturity waits this long past the window end so it lands
# first; a completed date is never revisited, so a positive that arrives later than this
# reads as a negative.
OUTCOME_INGESTION_GRACE = timedelta(hours=1)


def matures_at(prediction_date: date, horizon_days: int) -> datetime:
    """The first instant online validation can check a prediction date scored under ``horizon_days``."""
    window_start = datetime(prediction_date.year, prediction_date.month, prediction_date.day, tzinfo=UTC)
    return window_start + timedelta(days=horizon_days) + OUTCOME_INGESTION_GRACE
