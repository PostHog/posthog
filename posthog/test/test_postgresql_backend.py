from unittest import mock

from django.db import connections
from django.test import TestCase

from posthog.db_backends.postgresql.base import CONNECTION_OPEN_METRIC


class TestPostgresqlBackend(TestCase):
    def test_opening_a_connection_records_how_long_it_took(self) -> None:
        connection = connections.create_connection("default")
        self.addCleanup(connection.close)

        with mock.patch("posthog.db_backends.postgresql.base.posthoganalytics") as analytics:
            connection.connect()

        analytics.default_client.metrics.histogram.assert_called_once_with(
            CONNECTION_OPEN_METRIC, mock.ANY, unit="us", attributes={"alias": "default"}
        )
