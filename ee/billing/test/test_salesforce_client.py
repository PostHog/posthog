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


class TestGetSalesforceClient:
    @override_settings(
        SALESFORCE_INTERNAL_CONSUMER_KEY="test-consumer-key",
        SALESFORCE_INTERNAL_CONSUMER_SECRET="test-consumer-secret",
        SALESFORCE_INTERNAL_DOMAIN="test.my.salesforce.com",
    )
    @patch("ee.billing.salesforce_enrichment.salesforce_client.Salesforce")
    @patch("ee.billing.salesforce_enrichment.salesforce_client.requests.post")
    def test_uses_oauth_when_client_credentials_set(self, mock_post, mock_sf):
        mock_post.return_value = _mock_token_response()

        get_salesforce_client()

        mock_post.assert_called_once()
        call_data = mock_post.call_args[1]["data"]
        assert call_data["grant_type"] == "client_credentials"
        assert call_data["client_id"] == "test-consumer-key"
        assert call_data["client_secret"] == "test-consumer-secret"

        mock_sf.assert_called_once()
        sf_kwargs = mock_sf.call_args[1]
        assert sf_kwargs["session_id"] == "oauth-access-token-xyz"
        assert sf_kwargs["instance_url"] == "https://test.my.salesforce.com"

    @override_settings(
        SALESFORCE_INTERNAL_CONSUMER_KEY="test-consumer-key",
        SALESFORCE_INTERNAL_CONSUMER_SECRET="test-consumer-secret",
        SALESFORCE_INTERNAL_DOMAIN="test.my.salesforce.com",
    )
    @patch("ee.billing.salesforce_enrichment.salesforce_client.Salesforce")
    @patch("ee.billing.salesforce_enrichment.salesforce_client.requests.post")
    def test_posts_to_correct_token_endpoint(self, mock_post, mock_sf):
        mock_post.return_value = _mock_token_response()

        get_salesforce_client()

        assert mock_post.call_args[0][0] == "https://test.my.salesforce.com/services/oauth2/token"

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
    @patch("ee.billing.salesforce_enrichment.salesforce_client.requests.post")
    def test_prefers_oauth_when_both_credentials_set(self, mock_post, mock_sf):
        mock_post.return_value = _mock_token_response()

        get_salesforce_client()

        mock_post.assert_called_once()
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
    @patch("ee.billing.salesforce_enrichment.salesforce_client.requests.post")
    def test_raises_on_token_exchange_failure(self, mock_post, mock_sf):
        response = MagicMock(spec=requests.Response)
        response.status_code = 401
        response.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")
        mock_post.return_value = response

        with pytest.raises(requests.HTTPError):
            get_salesforce_client()

        mock_sf.assert_not_called()
