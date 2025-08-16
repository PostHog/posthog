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

    def test_client_requires_token(self):
        with self.assertRaises(ValueError):
            VercelAPIClient("")

    @patch("ee.vercel.client.requests.Session.post")
    def test_create_experimentation_items(self, mock_post):
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

    @patch("ee.vercel.client.requests.Session.patch")
    def test_update_experimentation_item(self, mock_patch):
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

    @patch("ee.vercel.client.requests.Session.delete")
    def test_delete_experimentation_item(self, mock_delete):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        result = self.client.delete_experimentation_item(self.integration_config_id, self.resource_id, self.item_id)

        assert result is True
        mock_delete.assert_called_once_with(
            f"{self.client.BASE_URL}/installations/{self.integration_config_id}/resources/{self.resource_id}/experimentation/items/{self.item_id}"
        )

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
        ]
    )
    @patch("ee.vercel.client.requests.Session.post")
    def test_sso_token_exchange(self, _name, kwargs, expected_data, mock_post):
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
