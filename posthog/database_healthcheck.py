import time
from typing import Optional

from django.conf import settings
from django.db import connections

import structlog

DATABASE_FOR_FLAG_MATCHING = (
    "default" if ("decide" not in settings.READ_REPLICA_OPT_IN or "replica" not in settings.DATABASES) else "replica"
)


logger = structlog.get_logger(__name__)


class DatabaseHealthcheck:
    """
    This class is used to check the health of the database.
    The time_interval is the time in seconds between checks.
    """

    def __init__(self, time_interval: int = 20) -> None:
        self.connected: bool = True
        self.last_check: Optional[int] = None
        self.time_interval = time_interval
        self.hits = 0
        self.misses = 0

    def cache_clear(self) -> None:
        self.hits = 0
        self.misses = 0

    def set_connection(self, connected: bool) -> None:
        self.connected = connected
        self.last_check = self._get_timebucket()
        self.cache_clear()

    def is_connected(self) -> bool:
        current_time_bucket = self._get_timebucket()
        if self.last_check != current_time_bucket:
            self.last_check = current_time_bucket
            self.connected = self.is_postgres_connected_check()
            self.misses += 1
        else:
            self.hits += 1

        return self.connected

    def _get_timebucket(self) -> int:
        return round(time.time() / self.time_interval)

    def is_postgres_connected_check(self) -> bool:
        try:
            with connections[DATABASE_FOR_FLAG_MATCHING].cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception as e:
            logger.exception(
                "postgres_connection_failure", error=str(e), database=DATABASE_FOR_FLAG_MATCHING, exc_info=True
            )
            return False


postgres_healthcheck = DatabaseHealthcheck(time_interval=30)
