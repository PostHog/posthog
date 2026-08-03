import pytest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.egress.composio.observability import normalize_composio_endpoint
from posthog.egress.composio.transport import ComposioEgressBudgetExhausted, composio_request
from posthog.egress.limiter.policies import Priority


class TestComposioEgress(SimpleTestCase):
    def _session_request(self) -> requests.Response:
        return composio_request(
            "POST",
            "/api/v3.1/tool_router/session",
            source="mcp_store",
            team_id=7,
            priority=Priority.NORMAL,
            json={"user_id": "u"},
        )

    @parameterized.expand(
        [
            (
                "session_create",
                "https://backend.composio.dev/api/v3.1/tool_router/session",
                "/api/v3.1/tool_router/session",
            ),
            (
                "connected_account_nano_id",
                "https://backend.composio.dev/api/v3/connected_accounts/ca_A1b2C3d4E5",
                "/api/v3/connected_accounts/{id}",
            ),
            (
                "opaque_session_id",
                "https://backend.composio.dev/api/v3.1/tool_router/session/aB3xK9mQ2zR7tY1w",
                "/api/v3.1/tool_router/session/{id}",
            ),
            ("numeric_id", "https://backend.composio.dev/api/v3/toolkits/42", "/api/v3/toolkits/{id}"),
            ("no_ids", "https://backend.composio.dev/api/v3/toolkits", "/api/v3/toolkits"),
        ]
    )
    def test_endpoint_label_templates_out_per_object_ids(self, _name: str, url: str, expected: str) -> None:
        assert normalize_composio_endpoint(url) == expected

    @parameterized.expand(
        [
            ("both_budgets_admit", True, True, False),
            ("team_budget_exhausted", True, False, True),
            ("account_budget_exhausted", False, True, True),
        ]
    )
    @override_settings(COMPOSIO_API_KEY="ck_test")
    def test_sheddable_call_is_denied_when_either_budget_is_spent(
        self, _name: str, account_granted: bool, team_granted: bool, expect_shed: bool
    ) -> None:
        response = requests.Response()
        response.status_code = 200

        with (
            patch("posthog.egress.composio.transport.consume_composio_account_sync", return_value=account_granted),
            patch("posthog.egress.composio.transport.consume_composio_team_sync", return_value=team_granted),
            patch("requests.request", return_value=response) as request,
            patch("posthog.egress.composio.transport.record_composio_api_response"),
        ):
            if expect_shed:
                with pytest.raises(ComposioEgressBudgetExhausted):
                    self._session_request()
            else:
                self._session_request()

        assert request.called is not expect_shed
        if not expect_shed:
            # Composio authenticates on x-api-key, unlike the Bearer-token domains next door.
            assert request.call_args.kwargs["headers"]["x-api-key"] == "ck_test"
