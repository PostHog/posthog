"""Wiring test for ``discover_posthog_code_repository_via_agent_activity``.

The selection agent's prompt, the cascade in front of it, and the outcome mapping are covered
elsewhere. What matters here is that the Slack path hands the project's wrong-repo corrections
to the shared agent, the same way the Self-driving chokepoint does.
"""

import pytest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.temporal.ai.slack_app.activities.repo_selection import discover_posthog_code_repository_via_agent_activity
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionWorkflowInputs

from products.tasks.backend.facade.repo_selection import RepoSelectionResult

CORRECTIONS_BLOCK = (
    "- 2026-09-01: a report selected `acme/monolith`; a reviewer dismissed it as the wrong repository "
    "and named `acme/mobile-sdk` instead."
)


@pytest.fixture
def integration(db):
    organization = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=organization, name="Team")
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T_WS",
        sensitive_config={"access_token": "xoxb"},
    )


class TestDiscoverRepositoryViaAgentActivity:
    def test_hands_the_teams_corrections_to_the_selection_agent(self, integration, activity_environment):
        select = AsyncMock(return_value=RepoSelectionResult(repository="acme/mobile-sdk", reason="ok"))
        inputs = PostHogCodeSlackMentionWorkflowInputs(
            event={},
            integration_id=integration.id,
            slack_team_id=integration.integration_id or "",
            user_id=1,
        )
        with (
            patch(
                "products.signals.backend.facade.api.wrong_repo_corrections_block", return_value=CORRECTIONS_BLOCK
            ) as block,
            patch("products.tasks.backend.facade.repo_selection.select_repository", new=select),
        ):
            outcome = async_to_sync(activity_environment.run)(
                discover_posthog_code_repository_via_agent_activity,
                inputs,
                "C123",
                {},  # no ``ts``, so the activity attempts no Slack reaction
                [{"user": "alice", "text": "investigate the mobile replay crash"}],
                1,
            )

        assert outcome.status == "found"
        assert outcome.repository == "acme/mobile-sdk"
        block.assert_called_once_with(integration.team_id)
        assert select.await_args is not None
        assert select.await_args.kwargs["past_corrections"] == CORRECTIONS_BLOCK
