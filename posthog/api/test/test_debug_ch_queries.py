from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN


class TestDebugCHQuery(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_denied(self):
        with patch("posthog.api.debug_ch_queries.is_cloud", return_value=True):
            with patch("posthog.api.debug_ch_queries.DEBUG", True):
                resp = self.client.get("/api/debug_ch_queries/")
                self.assertEqual(resp.status_code, HTTP_200_OK)

            with patch("posthog.api.debug_ch_queries.DEBUG", False):
                resp = self.client.get("/api/debug_ch_queries/")
                self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

            self.user.is_staff = True
            self.user.save()

            resp = self.client.get("/api/debug_ch_queries/")
            self.assertEqual(resp.status_code, HTTP_200_OK)

        with patch("posthog.api.debug_ch_queries.is_cloud", return_value=False):
            resp = self.client.get("/api/debug_ch_queries/")
            self.assertEqual(resp.status_code, HTTP_200_OK)
