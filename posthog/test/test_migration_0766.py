import uuid
from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class FixSubTemplateIdsToTemplateIdsMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0765_hogflows"
    migrate_to = "0766_fix_sub_template_ids_to_template_ids"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        HogFunction = apps.get_model("posthog", "HogFunction")

        self.organization = Organization.objects.create(name="o1")
        self.project = Project.objects.create(organization=self.organization, name="p1", id=1000001)
        self.team = Team.objects.create(organization=self.organization, name="t1", project=self.project)

        # Create HogFunctions with sub-template IDs
        self.hf_slack = HogFunction.objects.create(
            id=uuid.uuid4(),
            team=self.team,
            template_id="template-slack-error-tracking-issue-created",
            hog="return event",
        )
        self.hf_discord = HogFunction.objects.create(
            id=uuid.uuid4(),
            team=self.team,
            template_id="template-discord-survey-response",
            hog="return event",
        )
        self.hf_webhook = HogFunction.objects.create(
            id=uuid.uuid4(),
            team=self.team,
            template_id="template-webhook-error-tracking-issue-reopened",
            hog="return event",
        )
        self.hf_teams = HogFunction.objects.create(
            id=uuid.uuid4(),
            team=self.team,
            template_id="template-microsoft-teams-error-tracking-issue-created",
            hog="return event",
        )

    def test_migration(self):
        # After migration, all template_ids should be mapped to their parent
        self.hf_slack.refresh_from_db()
        self.hf_discord.refresh_from_db()
        self.hf_webhook.refresh_from_db()
        self.hf_teams.refresh_from_db()
        assert self.hf_slack.template_id == "template-slack"
        assert self.hf_discord.template_id == "template-discord"
        assert self.hf_webhook.template_id == "template-webhook"
        assert self.hf_teams.template_id == "template-microsoft-teams"
