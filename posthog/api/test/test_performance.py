"""
Tests for the Performance API endpoints.

Tests the core functionality requested in Issue #19686:
- Making network performance data queryable
- Filtering by status code, response time, parent page, target URL, resource type
"""

from datetime import datetime
from unittest.mock import patch

from rest_framework import status

from posthog.api.test.test_team import APIBaseTest
from posthog.test.base import ClickhouseTestMixin


class TestPerformanceAPI(ClickhouseTestMixin, APIBaseTest):
    """Test performance API endpoints as requested in Issue #19686."""

    def setUp(self):
        super().setUp()

        # Create mock performance data matching ClickHouse schema
        fixed_datetime = datetime(2024, 1, 15, 12, 0, 0)
        self.mock_performance_data = [
            (
                "uuid-1", "session-123", fixed_datetime, "https://example.com/api/users",
                "resource", 250.5, 200, 1024, "fetch", "https://example.com"
            ),
            (
                "uuid-2", "session-123", fixed_datetime, "https://example.com/api/posts",
                "resource", 150.2, 404, 512, "xmlhttprequest", "https://example.com"
            ),
        ]

    @patch("posthog.api.performance.sync_execute")
    def test_list_performance_events(self, mock_sync_execute):
        """Test basic listing of performance events."""
        mock_sync_execute.return_value = self.mock_performance_data

        response = self.client.get(f"/api/projects/{self.team.id}/performance/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 2)

        # Check that required fields from Issue #19686 are present
        first_result = data["results"][0]
        self.assertIn("name", first_result)  # Target URL
        self.assertIn("entry_type", first_result)  # Resource type
        self.assertIn("duration", first_result)  # Response time
        self.assertIn("response_status", first_result)  # Network status code
        self.assertIn("current_url", first_result)  # Parent page

    @patch("posthog.api.performance.sync_execute")
    def test_filter_by_network_status_code(self, mock_sync_execute):
        """Test filtering by network status code as requested in issue."""
        mock_sync_execute.return_value = [self.mock_performance_data[1]]  # 404 result

        response = self.client.get(
            f"/api/projects/{self.team.id}/performance/?response_status=404"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the SQL query includes status filter
        mock_sync_execute.assert_called_once()
        query_args = mock_sync_execute.call_args
        query = query_args[0][0]
        params = query_args[0][1]

        self.assertIn("response_status = %(response_status)s", query)
        self.assertEqual(params["response_status"], 404)

    @patch("posthog.api.performance.sync_execute")
    def test_filter_by_target_url(self, mock_sync_execute):
        """Test filtering by target URL as requested in issue."""
        mock_sync_execute.return_value = [self.mock_performance_data[0]]

        response = self.client.get(
            f"/api/projects/{self.team.id}/performance/?url_filter=users"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the SQL query includes URL filter
        mock_sync_execute.assert_called_once()
        query_args = mock_sync_execute.call_args
        query = query_args[0][0]
        params = query_args[0][1]

        self.assertIn("name ILIKE %(url_filter)s", query)
        self.assertEqual(params["url_filter"], "%users%")

    @patch("posthog.api.performance.sync_execute")
    def test_filter_by_resource_type(self, mock_sync_execute):
        """Test filtering by resource type (initiator_type) as requested in issue."""
        mock_sync_execute.return_value = [self.mock_performance_data[0]]

        response = self.client.get(
            f"/api/projects/{self.team.id}/performance/?initiator_type=fetch"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the SQL query includes initiator_type filter
        mock_sync_execute.assert_called_once()
        query_args = mock_sync_execute.call_args
        query = query_args[0][0]
        params = query_args[0][1]

        self.assertIn("initiator_type = %(initiator_type)s", query)
        self.assertEqual(params["initiator_type"], "fetch")

    @patch("posthog.api.performance.sync_execute")
    def test_filter_by_session_id(self, mock_sync_execute):
        """Test filtering by session ID for session-specific queries."""
        mock_sync_execute.return_value = self.mock_performance_data

        response = self.client.get(
            f"/api/projects/{self.team.id}/performance/?session_id=session-123"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the SQL query includes session_id filter
        mock_sync_execute.assert_called_once()
        query_args = mock_sync_execute.call_args
        query = query_args[0][0]
        params = query_args[0][1]

        self.assertIn("session_id = %(session_id)s", query)
        self.assertEqual(params["session_id"], "session-123")

    def test_permission_required(self):
        """Test that proper permissions are required."""
        other_user = self.create_user("other@example.com")
        self.client.force_login(other_user)

        response = self.client.get(f"/api/projects/{self.team.id}/performance/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("posthog.api.performance.sync_execute")
    def test_pagination_support(self, mock_sync_execute):
        """Test pagination parameters work correctly."""
        mock_sync_execute.return_value = self.mock_performance_data

        response = self.client.get(
            f"/api/projects/{self.team.id}/performance/?limit=10&offset=0"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify pagination parameters are passed to query
        mock_sync_execute.assert_called_once()
        query_args = mock_sync_execute.call_args
        params = query_args[0][1]

        self.assertEqual(params["limit"], 10)
        self.assertEqual(params["offset"], 0)
