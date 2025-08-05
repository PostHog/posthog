from unittest import TestCase
from unittest.mock import MagicMock, patch
from parameterized import parameterized
from ee.vercel.client import VercelAPIClient


class TestVercelAPIClient(TestCase):
    def setUp(self):
        super().setUp()
        self.client = VercelAPIClient("test_token")
        self.integration_config_id = "config_123"
        self.resource_id = "resource_456"
        self.item_id = "item_789"

    def test_client_initialization(self):
        client = VercelAPIClient("my_token")
        assert client.bearer_token == "my_token"
        assert client.BASE_URL == "https://api.vercel.com/v1"
        assert client.session.headers["Authorization"] == "Bearer my_token"
        assert client.session.headers["Content-Type"] == "application/json"

    def test_client_initialization_with_default_token(self):
        client = VercelAPIClient()
        assert client.bearer_token == "mock_token"

    @patch("ee.vercel.client.requests.Session.post")
    def test_create_experimentation_items_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response

        items = [{"id": "test", "slug": "test-slug", "origin": "test-origin"}]
        result = self.client.create_experimentation_items(self.integration_config_id, self.resource_id, items)

        assert result is True
        mock_post.assert_called_once_with(
            f"{self.client.BASE_URL}/installations/{self.integration_config_id}/resources/{self.resource_id}/experimentation/items",
            json={"items": items},
        )

    @patch("ee.vercel.client.requests.Session.post")
    def test_create_experimentation_items_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        items = [{"id": "test"}]
        result = self.client.create_experimentation_items(self.integration_config_id, self.resource_id, items)

        assert result is False

    @patch("ee.vercel.client.requests.Session.post")
    def test_create_experimentation_items_exception(self, mock_post):
        mock_post.side_effect = Exception("Network error")

        items = [{"id": "test"}]
        result = self.client.create_experimentation_items(self.integration_config_id, self.resource_id, items)

        assert result is False

    @patch("ee.vercel.client.requests.Session.patch")
    def test_update_experimentation_item_success(self, mock_patch):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_patch.return_value = mock_response

        data = {"slug": "updated-slug", "origin": "updated-origin"}
        result = self.client.update_experimentation_item(
            self.integration_config_id, self.resource_id, self.item_id, data
        )

        assert result is True
        mock_patch.assert_called_once_with(
            f"{self.client.BASE_URL}/installations/{self.integration_config_id}/resources/{self.resource_id}/experimentation/items/{self.item_id}",
            json=data,
        )

    @patch("ee.vercel.client.requests.Session.patch")
    def test_update_experimentation_item_failure(self, mock_patch):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_patch.return_value = mock_response

        data = {"slug": "updated-slug"}
        result = self.client.update_experimentation_item(
            self.integration_config_id, self.resource_id, self.item_id, data
        )

        assert result is False

    @patch("ee.vercel.client.requests.Session.patch")
    def test_update_experimentation_item_exception(self, mock_patch):
        mock_patch.side_effect = Exception("Network error")

        data = {"slug": "updated-slug"}
        result = self.client.update_experimentation_item(
            self.integration_config_id, self.resource_id, self.item_id, data
        )

        assert result is False

    @patch("ee.vercel.client.requests.Session.delete")
    def test_delete_experimentation_item_success(self, mock_delete):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        result = self.client.delete_experimentation_item(self.integration_config_id, self.resource_id, self.item_id)

        assert result is True
        mock_delete.assert_called_once_with(
            f"{self.client.BASE_URL}/installations/{self.integration_config_id}/resources/{self.resource_id}/experimentation/items/{self.item_id}"
        )

    @patch("ee.vercel.client.requests.Session.delete")
    def test_delete_experimentation_item_failure(self, mock_delete):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_delete.return_value = mock_response

        result = self.client.delete_experimentation_item(self.integration_config_id, self.resource_id, self.item_id)

        assert result is False

    @patch("ee.vercel.client.requests.Session.delete")
    def test_delete_experimentation_item_exception(self, mock_delete):
        mock_delete.side_effect = Exception("Network error")

        result = self.client.delete_experimentation_item(self.integration_config_id, self.resource_id, self.item_id)

        assert result is False

    @parameterized.expand(
        [
            (
                "minimal_params",
                {"code": "auth_code", "client_id": "client_123", "client_secret": "secret_456"},
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "grant_type": "authorization_code",
                },
            ),
            (
                "all_params",
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "state": "state_789",
                    "redirect_uri": "https://example.com/callback",
                    "grant_type": "custom_grant",
                },
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "grant_type": "custom_grant",
                    "state": "state_789",
                    "redirect_uri": "https://example.com/callback",
                },
            ),
        ]
    )
    @patch("ee.vercel.client.requests.Session.post")
    def test_sso_token_exchange_success(self, _name, kwargs, expected_data, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "id_token": "test_id_token",
            "token_type": "Bearer",
        }
        mock_post.return_value = mock_response

        result = self.client.sso_token_exchange(**kwargs)

        assert result == {"access_token": "test_access_token", "id_token": "test_id_token", "token_type": "Bearer"}
        mock_post.assert_called_once_with(
            f"{self.client.BASE_URL}/integrations/sso/token",
            data=expected_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    @parameterized.expand(
        [
            ("api_error", {"side_effect": None, "status_code": 400, "text": "Invalid authorization code"}),
            ("network_exception", {"side_effect": Exception("Network error"), "status_code": None, "text": None}),
        ]
    )
    @patch("ee.vercel.client.requests.Session.post")
    def test_sso_token_exchange_failures(self, _name, error_config, mock_post):
        if error_config["side_effect"]:
            mock_post.side_effect = error_config["side_effect"]
        else:
            mock_response = MagicMock()
            mock_response.status_code = error_config["status_code"]
            mock_response.text = error_config["text"]
            mock_post.return_value = mock_response

        result = self.client.sso_token_exchange("invalid_code", "client_123", "secret_456")

        assert result is None
