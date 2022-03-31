import datetime
from typing import Optional

import structlog

from posthog.settings import CONSTANCE_CONFIG, OBJECT_STORAGE_SESSION_RECORDING_BUCKET
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)
from posthog.internal_metrics import gauge


def delete_session_recording_files_order_than_ttl():
    """
        The clickhouse table has a TTL of a number of weeks before session recordings are deleted.
        The recordings are stored in a confgiurable bucket, and within that in sub-buckets named by date (YYYY-MM-DD)
        Once those buckets are older than the TTL, they can be deleted
    """

    ttl_weeks: Optional[int] = None
    file_deletion_time_delta: Optional[datetime.timedelta] = None
    try:
        ttl_setting = CONSTANCE_CONFIG["RECORDINGS_TTL_WEEKS"]
        ttl_weeks = ttl_setting[0]

        if not isinstance(ttl_weeks, int):
            raise ValueError("`CONSTANCE_CONFIG['RECORDINGS_TTL_WEEKS']` must be an integer")

        file_deletion_time_delta = datetime.timedelta(weeks=ttl_weeks, days=1)
        ttl_date = (datetime.datetime.now() - file_deletion_time_delta).date()
        number_of_deletions = object_storage.delete_older_than(ttl_date, prefix=OBJECT_STORAGE_SESSION_RECORDING_BUCKET)
        gauge("posthog_celery_session_recordings_deletion", number_of_deletions)
    except Exception as e:
        logger.error(
            "session_recordings_file_deletion_failed",
            ttl_weeks=ttl_weeks,
            file_deletion_time_delta=str(file_deletion_time_delta),
            exception=e,
        )
