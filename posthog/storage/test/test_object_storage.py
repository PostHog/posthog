from unittest.mock import patch

from posthog.storage.object_storage import health_check
from posthog.test.base import APIBaseTest


class TestStorage(APIBaseTest):
    @patch("posthog.storage.object_storage.client")
    def test_does_not_create_client_if_storage_is_disabled(self, patched_s3_client) -> None:
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            self.assertFalse(health_check())
            patched_s3_client.assert_not_called()
