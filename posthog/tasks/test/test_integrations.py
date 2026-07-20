import time
from typing import Optional

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.tasks.integrations import refresh_integration, refresh_integrations


class TestIntegrationsTasks(APIBaseTest):
    integrations: list[Integration] = []

    def setUp(self) -> None:
        super().setUp()

    def create_integration(
        self, kind: str, config: Optional[dict] = None, sensitive_config: Optional[dict] = None
    ) -> Integration:
        _config = {"refreshed_at": int(time.time()), "expires_in": 3600}
        _sensitive_config = {"refresh_token": "REFRESH"}
        _config.update(config or {})
        _sensitive_config.update(sensitive_config or {})

        return Integration.objects.create(team=self.team, kind=kind, config=_config, sensitive_config=_sensitive_config)

    def test_refresh_integrations_schedules_refreshes_for_expired(self) -> None:
        _integration_1 = self.create_integration("other")  # not an oauth one
        _integration_2 = self.create_integration("slack")  # not expired
        integration_3 = self.create_integration("slack", config={"refreshed_at": time.time() - 3600})  # expired
        integration_4 = self.create_integration(
            "slack", config={"refreshed_at": time.time() - 3600 + 170}
        )  # expired with buffer

        with patch("posthog.tasks.integrations.refresh_integration.delay") as refresh_integration_mock:
            refresh_integrations()
            # Both 3 and 4 should be refreshed
            assert refresh_integration_mock.call_args_list == [((integration_3.id,),), ((integration_4.id,),)]

    def test_refresh_integrations_skips_backed_off_and_terminal(self) -> None:
        expired = {"refreshed_at": time.time() - 3600}
        eligible = self.create_integration("slack", config=expired)
        backoff_elapsed = self.create_integration(
            "slack",
            config={**expired, "refresh_failure_count": 2, "refresh_next_attempt_at": int(time.time()) - 10},
        )
        _backed_off = self.create_integration(
            "slack",
            config={**expired, "refresh_failure_count": 2, "refresh_next_attempt_at": int(time.time()) + 300},
        )
        _terminal = self.create_integration(
            "slack", config={**expired, "refresh_failure_count": 5, "refresh_terminal": True}
        )

        with patch("posthog.tasks.integrations.refresh_integration.delay") as refresh_integration_mock:
            refresh_integrations()

        assert refresh_integration_mock.call_args_list == [((eligible.id,),), ((backoff_elapsed.id,),)]

    def test_refresh_integration_skips_when_backed_off(self) -> None:
        integration = self.create_integration(
            "slack",
            config={
                "refreshed_at": time.time() - 3600,
                "refresh_failure_count": 1,
                "refresh_next_attempt_at": int(time.time()) + 300,
            },
        )

        with patch("posthog.models.integration.OauthIntegration.refresh_access_token") as refresh_mock:
            refresh_integration(integration.id)

        assert refresh_mock.called is False

    @parameterized.expand(
        [
            ("expired", int(time.time()) - 3600, True),
            ("fresh", int(time.time()), False),
        ]
    )
    def test_refresh_integration_mints_only_when_still_expired(
        self, _name: str, refreshed_at: float, expected_refreshed: bool
    ) -> None:
        # Duplicate tasks can queue up for one row under backlog; refresh_integration must re-check the
        # just-loaded row so a task that finds it already fresh skips the mint instead of re-minting.
        integration = self.create_integration("github", config={"refreshed_at": refreshed_at, "expires_in": 3600})

        with patch("posthog.models.integration.GitHubIntegration.refresh_access_token") as refresh_mock:
            refresh_integration(integration.id)

        assert refresh_mock.called is expected_refreshed
