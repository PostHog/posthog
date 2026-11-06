import time

from django.db.backends.postgresql.base import DatabaseWrapper as PostgresDatabaseWrapper

import posthoganalytics

CONNECTION_OPEN_METRIC = "postgres.connection.open.duration"
MICROSECONDS_PER_SECOND = 1_000_000


class DatabaseWrapper(PostgresDatabaseWrapper):
    def connect(self) -> None:
        started_at = time.perf_counter()
        super().connect()
        client = posthoganalytics.default_client
        if client is None:
            return
        client.metrics.histogram(
            CONNECTION_OPEN_METRIC,
            (time.perf_counter() - started_at) * MICROSECONDS_PER_SECOND,
            unit="us",
            attributes={"alias": self.alias},
        )
