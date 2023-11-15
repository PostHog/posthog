from posthog.test.base import (
    APIBaseTest,
)
from unittest.mock import patch
from posthog.warehouse.external_data_source.source import create_source


class TestSource(APIBaseTest):
    @patch("posthog.warehouse.external_data_source.source.send_request")
    def test_create_stripe_source(self, send_request_mock):
        send_request_mock.return_value = {
            "sourceId": "123",
            "name": "stripe source",
            "sourceType": "stripe",
            "workspaceId": "456",
        }

        source_payload = {
            "account_id": "some_account_id",
            "client_secret": "some_secret",
        }

        data_source = create_source("stripe", source_payload, "456")

        self.assertEqual(data_source.source_id, "123")
        self.assertEqual(data_source.name, "stripe source")
        self.assertEqual(data_source.source_type, "stripe")
        self.assertEqual(data_source.workspace_id, "456")

    @patch("posthog.warehouse.external_data_source.source.send_request")
    def test_create_salesforce_source(self, send_request_mock):
        send_request_mock.return_value = {
            "sourceId": "123",
            "name": "salesforce source",
            "sourceType": "salesforce",
            "workspaceId": "456",
        }

        source_payload = {"client_id": "some_account_id", "client_secret": "some_secret", "refresh_token": "some_token"}

        data_source = create_source("salesforce", source_payload, "456")

        self.assertEqual(data_source.source_id, "123")
        self.assertEqual(data_source.name, "salesforce source")
        self.assertEqual(data_source.source_type, "salesforce")
        self.assertEqual(data_source.workspace_id, "456")

    @patch("posthog.warehouse.external_data_source.source.send_request")
    def test_create_postgres_source(self, send_request_mock):
        send_request_mock.return_value = {
            "sourceId": "123",
            "name": "postgres source",
            "sourceType": "postgres",
            "workspaceId": "456",
        }

        source_payload = {
            "host": "localhost",
            "port": 5432,
            "database": "test-db",
            "username": "posthog",
        }

        data_source = create_source("postgres", source_payload, "456")

        self.assertEqual(data_source.source_id, "123")
        self.assertEqual(data_source.name, "postgres source")
        self.assertEqual(data_source.source_type, "postgres")
        self.assertEqual(data_source.workspace_id, "456")
