from typing import Any

from unittest.mock import patch

from posthog.temporal.data_imports.sources.common.rest_source import rest_api_resources


def _minimal_config(base_url: str = "https://api.example.com") -> dict[str, Any]:
    return {
        "client": {"base_url": base_url},
        "resources": [
            {"name": "users", "primary_key": "id", "endpoint": {"path": "/users", "data_selector": "data"}},
        ],
    }


class TestRestApiResources:
    @patch("posthog.temporal.data_imports.sources.common.rest_source.RESTClient")
    def test_threads_team_id_to_rest_client(self, MockRESTClient) -> None:
        """create_resources must pass team_id to RESTClient — that hop is what
        gives allowlisted teams their SSRF exemption on REST-source syncs."""
        rest_api_resources(_minimal_config(), team_id=42, job_id="job-1", db_incremental_field_last_value=None)

        assert MockRESTClient.call_args.kwargs["team_id"] == 42
