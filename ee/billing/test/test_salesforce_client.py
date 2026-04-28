import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests

from ee.billing.salesforce_enrichment.salesforce_client import get_salesforce_client


def _mock_token_response():
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {
        "access_token": "oauth-access-token-xyz",
        "instance_url": "https://test.my.salesforce.com",
        "token_type": "Bearer",
    }
    response.raise_for_status = MagicMock()
    return response


def _mock_retry_session(token_response=None):
    """Build a mock session that returns the given token response on post()."""
    session = MagicMock(spec=requests.Session)
    if token_response is not None:
        session.post.return_value = token_response
    return session


class TestGetSalesforceClient:
    @override_settings(
        SALESFORCE_INTERNAL_CONSUMER_KEY="test-consumer-key",
        SALESFORCE_INTERNAL_CONSUMER_SECRET="test-consumer-secret",
        SALESFORCE_INTERNAL_DOMAIN="test.my.salesforce.com",
    )
    @patch("ee.billing.salesforce_enrichment.salesforce_client.Salesforce")
    @patch("ee.billing.salesforce_enrichment.salesforce_client._build_retry_session")
    def test_uses_oauth_when_client_credentials_set(self, mock_build_session, mock_sf):
        mock_session = _mock_retry_session(_mock_token_response())
        mock_build_session.return_value = mock_session

        get_salesforce_client()

        mock_session.post.assert_called_once()
        call_data = mock_session.post.call_args[1]["data"]
        assert call_data["grant_type"] == "client_credentials"
        assert call_data["client_id"] == "test-consumer-key"
        assert call_data["client_secret"] == "test-consumer-secret"

        mock_sf.assert_called_once()
        sf_kwargs = mock_sf.call_args[1]
        assert sf_kwargs["session_id"] == "oauth-access-token-xyz"
        assert sf_kwargs["instance_url"] == "https://test.my.salesforce.com"
        assert mock_session.post.call_args[0][0] == "https://test.my.salesforce.com/services/oauth2/token"

    @override_settings(
        SALESFORCE_INTERNAL_CONSUMER_KEY="",
        SALESFORCE_INTERNAL_CONSUMER_SECRET="",
        SALESFORCE_USERNAME="user@example.com",
        SALESFORCE_PASSWORD="password123",
        SALESFORCE_SECURITY_TOKEN="token456",
    )
    @patch("ee.billing.salesforce_enrichment.salesforce_client.Salesforce")
    def test_falls_back_to_legacy_when_no_oauth_credentials(self, mock_sf):
        get_salesforce_client()

        mock_sf.assert_called_once()
        sf_kwargs = mock_sf.call_args[1]
        assert sf_kwargs["username"] == "user@example.com"
        assert sf_kwargs["password"] == "password123"
        assert sf_kwargs["security_token"] == "token456"
        assert "session_id" not in sf_kwargs

    @override_settings(
        SALESFORCE_INTERNAL_CONSUMER_KEY="test-consumer-key",
        SALESFORCE_INTERNAL_CONSUMER_SECRET="test-consumer-secret",
        SALESFORCE_INTERNAL_DOMAIN="test.my.salesforce.com",
        SALESFORCE_USERNAME="user@example.com",
        SALESFORCE_PASSWORD="password123",
        SALESFORCE_SECURITY_TOKEN="token456",
    )
    @patch("ee.billing.salesforce_enrichment.salesforce_client.Salesforce")
    @patch("ee.billing.salesforce_enrichment.salesforce_client._build_retry_session")
    def test_prefers_oauth_when_both_credentials_set(self, mock_build_session, mock_sf):
        mock_session = _mock_retry_session(_mock_token_response())
        mock_build_session.return_value = mock_session

        get_salesforce_client()

        mock_session.post.assert_called_once()
        sf_kwargs = mock_sf.call_args[1]
        assert "session_id" in sf_kwargs
        assert "password" not in sf_kwargs

    @override_settings(
        SALESFORCE_INTERNAL_CONSUMER_KEY="",
        SALESFORCE_INTERNAL_CONSUMER_SECRET="",
        SALESFORCE_USERNAME="",
        SALESFORCE_PASSWORD="",
        SALESFORCE_SECURITY_TOKEN="",
    )
    def test_raises_value_error_when_no_credentials(self):
        with pytest.raises(ValueError, match="Missing Salesforce credentials"):
            get_salesforce_client()

    @override_settings(
        SALESFORCE_INTERNAL_CONSUMER_KEY="test-consumer-key",
        SALESFORCE_INTERNAL_CONSUMER_SECRET="test-consumer-secret",
        SALESFORCE_INTERNAL_DOMAIN="test.my.salesforce.com",
    )
    @patch("ee.billing.salesforce_enrichment.salesforce_client.Salesforce")
    @patch("ee.billing.salesforce_enrichment.salesforce_client._build_retry_session")
    def test_raises_on_token_exchange_failure(self, mock_build_session, mock_sf):
        response = MagicMock(spec=requests.Response)
        response.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized", response=response)
        mock_session = _mock_retry_session(response)
        mock_build_session.return_value = mock_session

        with pytest.raises(requests.HTTPError):
            get_salesforce_client()

        mock_sf.assert_not_called()
