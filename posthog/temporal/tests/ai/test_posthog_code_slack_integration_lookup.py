import pytest

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.temporal.ai.posthog_code_slack_mention import _get_posthog_code_slack_integration


@pytest.mark.django_db
class TestGetPosthogCodeSlackIntegration:
    """The helper must accept both Slack integration kinds.

    Workflows started during the c61131d → ce40d80 (2026-05-22) unification window
    persisted an integration_id pointing at the workspace's kind="slack" notifications
    row instead of the dedicated kind="slack-posthog-code" coding-agent row. After the
    revert the strict get() on kind="slack-posthog-code" raises DoesNotExist, Temporal
    retries it three times, and every cycle floods error tracking.
    """

    def _make_team(self) -> Team:
        org = Organization.objects.create(name="org")
        return Team.objects.create(organization=org, name="team")

    @pytest.mark.parametrize("kind", ["slack-posthog-code", "slack"])
    def test_returns_integration_for_either_slack_kind(self, kind: str) -> None:
        team = self._make_team()
        integration = Integration.objects.create(team=team, kind=kind, integration_id="T_WORKSPACE", config={})

        result = _get_posthog_code_slack_integration(integration.id, "T_WORKSPACE")

        assert result.id == integration.id
        assert result.kind == kind

    def test_rejects_non_slack_kinds_to_preserve_idor_scope(self) -> None:
        team = self._make_team()
        integration = Integration.objects.create(team=team, kind="github", integration_id="T_WORKSPACE", config={})

        with pytest.raises(Integration.DoesNotExist):
            _get_posthog_code_slack_integration(integration.id, "T_WORKSPACE")

    def test_rejects_wrong_slack_team_id(self) -> None:
        team = self._make_team()
        integration = Integration.objects.create(
            team=team, kind="slack-posthog-code", integration_id="T_RIGHT", config={}
        )

        with pytest.raises(Integration.DoesNotExist):
            _get_posthog_code_slack_integration(integration.id, "T_WRONG")
