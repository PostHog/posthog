from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.core.management import call_command

from posthog.models.integration import Integration


class TestBackfillGitHubOrganizationMetadata(BaseTest):
    def _github_integration(self, config: dict, integration_id: str) -> Integration:
        return Integration.objects.create(team=self.team, kind="github", integration_id=integration_id, config=config)

    @patch("posthog.models.github_metadata.posthoganalytics.group_identify")
    def test_projects_stored_facts_keyed_by_organization_uuid(self, mock_group_identify):
        self._github_integration(
            {
                "installation_id": "1",
                "repository_selection": "selected",
                "repository_count": 4,
                "account": {"type": "Organization", "name": "acme"},
            },
            "1",
        )

        call_command("backfill_github_organization_metadata")

        mock_group_identify.assert_called_once_with(
            "organization",
            str(self.team.organization_id),
            properties={
                "github_account_type": "organization",
                "github_repository_selection": "selected",
                "github_repository_count": 4,
            },
        )
        # Guard against regressing to the team id as the group key.
        assert mock_group_identify.call_args.args[1] != str(self.team.id)

    @patch("posthog.models.github_metadata.posthoganalytics.group_identify")
    def test_skips_rows_without_account_or_repository_data(self, mock_group_identify):
        self._github_integration({"installation_id": "2"}, "2")
        self._github_integration({"installation_id": "3", "account": {"name": "acme"}}, "3")

        call_command("backfill_github_organization_metadata")

        mock_group_identify.assert_not_called()

    @patch("posthog.models.github_metadata.posthoganalytics.group_identify")
    def test_dry_run_writes_nothing(self, mock_group_identify):
        self._github_integration({"installation_id": "4", "account": {"type": "User", "name": "octocat"}}, "4")

        call_command("backfill_github_organization_metadata", "--dry-run")

        mock_group_identify.assert_not_called()

    @patch("posthog.models.github_metadata.posthoganalytics.group_identify")
    def test_normalizes_personal_account_type(self, mock_group_identify):
        self._github_integration({"installation_id": "5", "account": {"type": "User", "name": "octocat"}}, "5")

        call_command("backfill_github_organization_metadata")

        assert mock_group_identify.call_args == call(
            "organization",
            str(self.team.organization_id),
            properties={"github_account_type": "personal"},
        )
