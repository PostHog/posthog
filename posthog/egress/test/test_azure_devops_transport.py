import pytest
from unittest.mock import MagicMock, patch

import requests

from posthog.egress.azure_devops import AZURE_DEVOPS_API_VERSION, AzureDevOpsAuthenticationError, AzureDevOpsClient


class TestAzureDevOpsClient:
    @patch("posthog.egress.azure_devops.transport.requests.request")
    def test_request_pins_host_and_pat_auth(self, mock_request: MagicMock) -> None:
        mock_request.return_value = MagicMock(status_code=200)

        AzureDevOpsClient("my-org", "pat-token", source="test", timeout=10).request(
            "GET",
            "/_apis/projects/project",
            endpoint="/_apis/projects/{project}",
        )

        args, kwargs = mock_request.call_args
        assert args == ("GET", "https://dev.azure.com/my-org/_apis/projects/project")
        assert kwargs["auth"] == ("", "pat-token")
        assert kwargs["allow_redirects"] is False
        assert kwargs["params"]["api-version"] == AZURE_DEVOPS_API_VERSION

    @patch("posthog.egress.azure_devops.transport.requests.request")
    def test_203_is_treated_as_authentication_failure(self, mock_request: MagicMock) -> None:
        mock_request.return_value = MagicMock(status_code=203)

        with pytest.raises(AzureDevOpsAuthenticationError, match="invalid or expired"):
            AzureDevOpsClient("my-org", "pat-token", source="test").request(
                "GET",
                "/_apis/projects",
                endpoint="/_apis/projects",
            )

    @patch("posthog.egress.azure_devops.transport.requests.request")
    def test_post_transport_error_is_not_retried(self, mock_request: MagicMock) -> None:
        mock_request.side_effect = requests.ConnectionError("connection dropped")

        with pytest.raises(requests.ConnectionError):
            AzureDevOpsClient("my-org", "pat-token", source="test").request(
                "POST",
                "/project/_apis/git/repositories/repo/refs",
                endpoint="/{project}/_apis/git/repositories/{repository}/refs",
                json=[],
            )

        mock_request.assert_called_once()
