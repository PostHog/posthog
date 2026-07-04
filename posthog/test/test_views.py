from unittest.mock import patch

from django.db import OperationalError
from django.test import Client, TestCase


class TestHealthView(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_health_returns_ok_when_migrations_uptodate(self):
        with patch("posthog.views.MigrationExecutor") as mock_executor:
            mock_executor.return_value.migration_plan.return_value = []
            response = self.client.get("/_health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_health_returns_503_when_migrations_pending(self):
        with patch("posthog.views.MigrationExecutor") as mock_executor:
            mock_executor.return_value.migration_plan.return_value = [("migration", False)]
            response = self.client.get("/_health/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"Migrations are not up to date")

    def test_health_returns_503_when_db_connection_fails(self):
        with patch("posthog.views.MigrationExecutor", side_effect=OperationalError("connection timeout expired")):
            response = self.client.get("/_health/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"Database is unavailable")
