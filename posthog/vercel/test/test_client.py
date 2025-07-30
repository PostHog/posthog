from unittest import TestCase
from unittest.mock import MagicMock, patch
from posthog.vercel.client import VercelAPIClient


class TestVercelAPIClient(TestCase):
    def setUp(self):
        super().setUp()
        self.client = VercelAPIClient("test_token")
        self.integration_config_id = "config_123"
        self.resource_id = "resource_456"
        self.item_id = "item_789"

    def test_client_initialization(self):
        client = VercelAPIClient("my_token")
        self.assertEqual(client.bearer_token, "my_token")
        self.assertEqual(client.BASE_URL, "https://api.vercel.com/v1")
        self.assertEqual(client.session.headers["Authorization"], "Bearer my_token")
        self.assertEqual(client.session.headers["Content-Type"], "application/json")

    def test_client_initialization_with_default_token(self):
        client = VercelAPIClient()
        self.assertEqual(client.bearer_token, "mock_token")

    @patch("posthog.vercel.client.requests.Session.post")
    def test_create_experimentation_items_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response

        items = [{"id": "test", "slug": "test-slug", "origin": "test-origin"}]
        result = self.client.create_experimentation_items(self.integration_config_id, self.resource_id, items)

        self.assertTrue(result)
        mock_post.assert_called_once_with(
            f"{self.client.BASE_URL}/installations/{self.integration_config_id}/resources/{self.resource_id}/experimentation/items",
            json={"items": items},
        )

    @patch("posthog.vercel.client.requests.Session.post")
    def test_create_experimentation_items_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        items = [{"id": "test"}]
        result = self.client.create_experimentation_items(self.integration_config_id, self.resource_id, items)

        self.assertFalse(result)

    @patch("posthog.vercel.client.requests.Session.post")
    def test_create_experimentation_items_exception(self, mock_post):
        mock_post.side_effect = Exception("Network error")

        items = [{"id": "test"}]
        result = self.client.create_experimentation_items(self.integration_config_id, self.resource_id, items)

        self.assertFalse(result)

    @patch("posthog.vercel.client.requests.Session.patch")
    def test_update_experimentation_item_success(self, mock_patch):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_patch.return_value = mock_response

        data = {"slug": "updated-slug", "origin": "updated-origin"}
        result = self.client.update_experimentation_item(
            self.integration_config_id, self.resource_id, self.item_id, data
        )

        self.assertTrue(result)
        mock_patch.assert_called_once_with(
            f"{self.client.BASE_URL}/installations/{self.integration_config_id}/resources/{self.resource_id}/experimentation/items/{self.item_id}",
            json=data,
        )

    @patch("posthog.vercel.client.requests.Session.patch")
    def test_update_experimentation_item_failure(self, mock_patch):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_patch.return_value = mock_response

        data = {"slug": "updated-slug"}
        result = self.client.update_experimentation_item(
            self.integration_config_id, self.resource_id, self.item_id, data
        )

        self.assertFalse(result)

    @patch("posthog.vercel.client.requests.Session.patch")
    def test_update_experimentation_item_exception(self, mock_patch):
        mock_patch.side_effect = Exception("Network error")

        data = {"slug": "updated-slug"}
        result = self.client.update_experimentation_item(
            self.integration_config_id, self.resource_id, self.item_id, data
        )

        self.assertFalse(result)

    @patch("posthog.vercel.client.requests.Session.delete")
    def test_delete_experimentation_item_success(self, mock_delete):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        result = self.client.delete_experimentation_item(self.integration_config_id, self.resource_id, self.item_id)

        self.assertTrue(result)
        mock_delete.assert_called_once_with(
            f"{self.client.BASE_URL}/installations/{self.integration_config_id}/resources/{self.resource_id}/experimentation/items/{self.item_id}"
        )

    @patch("posthog.vercel.client.requests.Session.delete")
    def test_delete_experimentation_item_failure(self, mock_delete):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_delete.return_value = mock_response

        result = self.client.delete_experimentation_item(self.integration_config_id, self.resource_id, self.item_id)

        self.assertFalse(result)

    @patch("posthog.vercel.client.requests.Session.delete")
    def test_delete_experimentation_item_exception(self, mock_delete):
        mock_delete.side_effect = Exception("Network error")

        result = self.client.delete_experimentation_item(self.integration_config_id, self.resource_id, self.item_id)

        self.assertFalse(result)

    def test_url_construction_create(self):
        with patch("posthog.vercel.client.requests.Session.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_post.return_value = mock_response

            self.client.create_experimentation_items("config_123", "resource_456", [])

            expected_url = (
                "https://api.vercel.com/v1/installations/config_123/resources/resource_456/experimentation/items"
            )
            mock_post.assert_called_once_with(expected_url, json={"items": []})

    def test_url_construction_update(self):
        with patch("posthog.vercel.client.requests.Session.patch") as mock_patch:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_patch.return_value = mock_response

            self.client.update_experimentation_item("config_123", "resource_456", "item_789", {})

            expected_url = "https://api.vercel.com/v1/installations/config_123/resources/resource_456/experimentation/items/item_789"
            mock_patch.assert_called_once_with(expected_url, json={})

    def test_url_construction_delete(self):
        with patch("posthog.vercel.client.requests.Session.delete") as mock_delete:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_delete.return_value = mock_response

            self.client.delete_experimentation_item("config_123", "resource_456", "item_789")

            expected_url = "https://api.vercel.com/v1/installations/config_123/resources/resource_456/experimentation/items/item_789"
            mock_delete.assert_called_once_with(expected_url)
