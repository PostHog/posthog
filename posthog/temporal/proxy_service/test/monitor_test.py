import json

import pytest
from freezegun import freeze_time
from unittest.mock import Mock, patch

from django.test import TestCase

import requests

from posthog.models import Organization, ProxyRecord
from posthog.temporal.proxy_service.monitor import CheckActivityInput, check_proxy_is_live


class TestCheckProxyIsLive(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.proxy_record = ProxyRecord.objects.create(
            organization=self.organization, domain="us.i.posthog.com", status="active"
        )
        self.input = CheckActivityInput(proxy_record_id=self.proxy_record.id)

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_success_live(self, mock_get_record):
        """Live test against us.i.posthog.com"""
        mock_get_record.return_value = self.proxy_record

        result = await check_proxy_is_live(self.input)

        # Should succeed without errors or warnings
        assert result.errors == []
        assert result.warnings == []

    @pytest.mark.asyncio
    @freeze_time("2024-01-16 10:00:00")  # Frozen at Jan 16, cert expires Feb 15 (30 days later)
    @patch("posthog.temporal.proxy_service.monitor.ssl.create_default_context")
    @patch("posthog.temporal.proxy_service.monitor.requests.post")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_success_mocked(self, mock_get_record, mock_post, mock_ssl_context):
        """Test successful proxy check with mocked dependencies"""
        mock_get_record.return_value = self.proxy_record

        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Mock SSL certificate check with fixed future date (20 days from frozen time)
        mock_cert = {"notAfter": "Feb  5 10:00:00 2024 GMT"}
        mock_socket = Mock()
        mock_socket.getpeercert.return_value = mock_cert

        mock_context = Mock()
        mock_wrapped_socket = Mock()
        mock_wrapped_socket.__enter__ = Mock(return_value=mock_socket)
        mock_wrapped_socket.__exit__ = Mock(return_value=None)
        mock_context.wrap_socket.return_value = mock_wrapped_socket
        mock_ssl_context.return_value = mock_context

        result = await check_proxy_is_live(self.input)

        # Verify the request was made correctly
        mock_post.assert_called_once_with(
            f"https://{self.proxy_record.domain}/i/v0/e/",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"event": "test", "api_key": "test", "distinct_id": "test"}),
        )

        assert result.errors == []
        assert result.warnings == []

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.requests.post")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_ssl_error(self, mock_get_record, mock_post):
        """Test SSL error handling"""
        mock_get_record.return_value = self.proxy_record
        mock_post.side_effect = requests.exceptions.SSLError("SSL certificate problem")

        result = await check_proxy_is_live(self.input)

        assert result.errors == ["Failed to connect to proxy: invalid SSL certificate"]
        assert result.warnings == []

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.requests.post")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_connection_error(self, mock_get_record, mock_post):
        """Test connection error handling"""
        mock_get_record.return_value = self.proxy_record
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        result = await check_proxy_is_live(self.input)

        assert result.errors == ["Failed to connect to proxy"]
        assert result.warnings == []

    @pytest.mark.asyncio
    @patch("posthog.temporal.proxy_service.monitor.requests.post")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_http_error(self, mock_get_record, mock_post):
        """Test HTTP error handling"""
        mock_get_record.return_value = self.proxy_record

        mock_response = Mock()
        mock_response.status_code = 500
        mock_post.side_effect = requests.exceptions.HTTPError(response=mock_response)

        result = await check_proxy_is_live(self.input)

        assert result.errors == ["Failed to send event to proxy, expected 200 but got 500"]
        assert result.warnings == []

    @pytest.mark.asyncio
    @freeze_time("2024-01-16 10:00:00")  # Frozen at Jan 16, cert expires Jan 25 (9 days later, < 14 day threshold)
    @patch("posthog.temporal.proxy_service.monitor.ssl.create_default_context")
    @patch("posthog.temporal.proxy_service.monitor.requests.post")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_cert_expiring_soon(self, mock_get_record, mock_post, mock_ssl_context):
        """Test certificate expiring soon warning"""
        mock_get_record.return_value = self.proxy_record

        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Mock SSL certificate that expires in 9 days (less than 14 day threshold)
        mock_cert = {"notAfter": "Jan 25 10:00:00 2024 GMT"}
        mock_socket = Mock()
        mock_socket.getpeercert.return_value = mock_cert

        mock_context = Mock()
        mock_wrapped_socket = Mock()
        mock_wrapped_socket.__enter__ = Mock(return_value=mock_socket)
        mock_wrapped_socket.__exit__ = Mock(return_value=None)
        mock_context.wrap_socket.return_value = mock_wrapped_socket
        mock_ssl_context.return_value = mock_context

        result = await check_proxy_is_live(self.input)

        assert result.errors == ["Live proxy certificate is expiring soon"]
        assert result.warnings == []
