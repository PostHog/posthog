from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework.status import HTTP_200_OK, HTTP_202_ACCEPTED, HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN


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


class TestDebugCHQueryProfile(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_non_staff_gets_403(self):
        self.user.is_staff = False
        self.user.save()
        resp = self.client.post("/api/debug_ch_queries/profile/", {"query": "SELECT 1"}, format="json")
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

    def test_rejects_empty_query(self):
        self.user.is_staff = True
        self.user.save()
        resp = self.client.post("/api/debug_ch_queries/profile/", {"query": ""}, format="json")
        self.assertEqual(resp.status_code, HTTP_400_BAD_REQUEST)

    @patch("posthog.api.debug_ch_queries.get_client_from_pool")
    def test_returns_profile_query_id(self, mock_get_client):
        self.user.is_staff = True
        self.user.save()

        mock_client = MagicMock()
        mock_get_client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_get_client.return_value.__exit__ = MagicMock(return_value=False)

        resp = self.client.post("/api/debug_ch_queries/profile/", {"query": "SELECT 1"}, format="json")
        self.assertEqual(resp.status_code, HTTP_200_OK)
        data = resp.json()
        self.assertIn("profile_query_id", data)
        self.assertIn("execution_time_ms", data)
        self.assertTrue(data["profile_query_id"].startswith("profile_"))


class TestDebugCHQueryProfileResults(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_non_staff_gets_403(self):
        self.user.is_staff = False
        self.user.save()
        resp = self.client.get("/api/debug_ch_queries/profile_results/?profile_query_id=test")
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

    def test_missing_query_id_gets_400(self):
        self.user.is_staff = True
        self.user.save()
        resp = self.client.get("/api/debug_ch_queries/profile_results/")
        self.assertEqual(resp.status_code, HTTP_400_BAD_REQUEST)

    @patch("posthog.api.debug_ch_queries.sync_execute")
    def test_returns_202_when_pending(self, mock_sync_execute):
        self.user.is_staff = True
        self.user.save()
        mock_sync_execute.return_value = []

        resp = self.client.get("/api/debug_ch_queries/profile_results/?profile_query_id=profile_abc")
        self.assertEqual(resp.status_code, HTTP_202_ACCEPTED)
        self.assertEqual(resp.json()["status"], "pending")

    @patch("posthog.api.debug_ch_queries.sync_execute")
    def test_returns_folded_stacks(self, mock_sync_execute):
        self.user.is_staff = True
        self.user.save()
        mock_sync_execute.return_value = [("main;foo;bar", 10), ("main;baz", 5)]

        resp = self.client.get("/api/debug_ch_queries/profile_results/?profile_query_id=profile_abc")
        self.assertEqual(resp.status_code, HTTP_200_OK)
        data = resp.json()
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["folded_stacks"], ["main;foo;bar 10", "main;baz 5"])
        self.assertEqual(data["sample_count"], 15)
