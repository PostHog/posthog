import pytest
from unittest.mock import patch

from products.conversations.backend.temporal.zendesk_import.client import (
    ZendeskCredentials,
    validate_zendesk_credentials,
)

M = "products.conversations.backend.temporal.zendesk_import.client"


class TestValidateZendeskCredentials:
    @pytest.mark.parametrize(
        "subdomain",
        [
            # A `#` turns the rest of the base URL into a fragment, so the real host would become
            # the attacker value instead of "<label>.zendesk.com" — the Basic auth token must not
            # be sent there.
            pytest.param("attacker.example#", id="host_fragment"),
            pytest.param("169.254.169.254#", id="metadata_ip_fragment"),
            pytest.param("foo.bar", id="multi_label"),
            pytest.param("foo@bar", id="userinfo"),
        ],
    )
    def test_rejects_host_retargeting_subdomain_without_request(self, subdomain: str) -> None:
        credentials = ZendeskCredentials(subdomain=subdomain, email_address="user@example.com", api_token="token")

        with patch(f"{M}.make_tracked_session") as mock_session:
            assert validate_zendesk_credentials(credentials) is False
            mock_session.assert_not_called()
