from importlib import import_module

from posthog.test.base import BaseTest

from django.db import connection
from django.db.migrations.loader import MigrationLoader

migration = import_module("posthog.migrations.1435_delete_user_interview_sharing_configurations")


class TestDeleteUserInterviewSharingConfigurations(BaseTest):
    # Later migrations drop foreign keys irreversibly, so TestMigrations cannot migrate back to
    # 1433. The tables and columns are still there, so run the data step against the models as
    # they were at 1434 instead.
    def test_deletes_only_the_shares_of_user_interviews(self) -> None:
        apps = (
            MigrationLoader(connection)
            .project_state(
                [
                    ("posthog", "1435_delete_user_interview_sharing_configurations"),
                    ("user_interviews", "0010_alter_intervieweecontext_team_and_more"),
                ]
            )
            .apps
        )
        SharingConfiguration = apps.get_model("posthog", "SharingConfiguration")
        UserInterviewTopic = apps.get_model("user_interviews", "UserInterviewTopic")
        IntervieweeContext = apps.get_model("user_interviews", "IntervieweeContext")

        topic = UserInterviewTopic.objects.create(team_id=self.team.id, topic="Onboarding")
        interviewee_context = IntervieweeContext.objects.create(
            team_id=self.team.id, topic=topic, interviewee_identifier="person@example.com", agent_context="context"
        )
        interview_share = SharingConfiguration.objects.create(
            team_id=self.team.id, interviewee_context=interviewee_context, enabled=True
        )
        team_wide_share = SharingConfiguration.objects.create(team_id=self.team.id, enabled=True)

        migration.delete_user_interview_sharing_configurations(apps, None)

        # Once Django stops tracking interviewee_context, an interview share looks like a team-wide
        # share, and its token would start to authenticate team-wide endpoints.
        assert not SharingConfiguration.objects.filter(id=interview_share.id).exists()
        assert SharingConfiguration.objects.filter(id=team_wide_share.id).exists()
