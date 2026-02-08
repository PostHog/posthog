from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client, override_settings

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog


class TestRedisEditTTLView(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)
        self.user.is_staff = True
        self.user.save()

    @parameterized.expand(
        [
            ("key_with_ttl", "test:cache:key", 3600, b"3600"),
            ("key_without_ttl", "persistent:key", -1, b"No TTL set"),
        ]
    )
    @override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
    @patch("posthog.views.get_client")
    def test_get_request_returns_form(
        self, _name: str, key: str, ttl_return: int, expected_content: bytes, mock_get_client: MagicMock
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.ttl.return_value = ttl_return
        mock_get_client.return_value = mock_redis

        response = self.client.get(f"/admin/redis/edit-ttl?key={key}")

        assert response.status_code == 200
        assert key.encode() in response.content
        assert expected_content in response.content

    @patch("posthog.views.get_client")
    def test_nonexistent_key_returns_404(self, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.ttl.return_value = -2
        mock_get_client.return_value = mock_redis

        response = self.client.get("/admin/redis/edit-ttl?key=nonexistent:key")

        assert response.status_code == 404
        assert b"Redis key not found" in response.content

    def test_missing_key_redirects(self) -> None:
        response = self.client.get("/admin/redis/edit-ttl")

        assert response.status_code == 302
        assert response["Location"] == "/admin/redisvalues"

    @parameterized.expand(
        [
            ("set_ttl", "7200", "expire", "ttl_updated", "Set TTL to 7200s on Redis key test:cache:key"),
            ("remove_ttl", "", "persist", "ttl_removed", "Removed TTL from Redis key test:cache:key"),
            ("negative_ttl", "-1", "expire", "ttl_updated", "Set TTL to -1s on Redis key test:cache:key"),
        ]
    )
    @patch("posthog.views.get_client")
    def test_post_creates_activity_log(
        self,
        _name: str,
        ttl_input: str,
        expected_method: str,
        expected_activity: str,
        expected_detail_name: str,
        mock_get_client: MagicMock,
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.ttl.return_value = 3600
        mock_get_client.return_value = mock_redis

        response = self.client.post(
            "/admin/redis/edit-ttl",
            data={"key": "test:cache:key", "ttl_seconds": ttl_input},
        )

        assert response.status_code == 302

        if expected_method == "expire":
            mock_redis.expire.assert_called_once_with("test:cache:key", int(ttl_input))
        else:
            mock_redis.persist.assert_called_once_with("test:cache:key")

        log = ActivityLog.objects.filter(scope="Admin", activity=expected_activity).latest("id")
        assert log.item_id == "test:cache:key"
        assert log.user == self.user
        assert log.organization_id == self.organization.id
        detail = log.detail
        assert detail is not None
        assert detail["name"] == expected_detail_name
        assert detail["type"] == "previous_ttl:3600"

    @parameterized.expand(
        [
            ("text",),
            ("1.5",),
            ("abc123",),
            ("12abc",),
        ]
    )
    @patch("posthog.views.get_client")
    def test_invalid_ttl_returns_400(self, invalid_ttl: str, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        response = self.client.post(
            "/admin/redis/edit-ttl",
            data={"key": "test:cache:key", "ttl_seconds": invalid_ttl},
        )

        assert response.status_code == 400
        assert b"Invalid TTL value" in response.content
        mock_redis.expire.assert_not_called()
        mock_redis.persist.assert_not_called()

    @parameterized.expand([("put",), ("patch",), ("delete",)])
    def test_disallowed_methods_return_405(self, method: str) -> None:
        response = getattr(self.client, method)("/admin/redis/edit-ttl?key=test:key")

        assert response.status_code == 405

    def test_post_without_csrf_token_returns_403(self) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            "/admin/redis/edit-ttl",
            data={"key": "test:cache:key", "ttl_seconds": "3600"},
        )

        assert response.status_code == 403
