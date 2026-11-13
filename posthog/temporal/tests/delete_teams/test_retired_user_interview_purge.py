import pytest

from django.db import connection
from django.db.migrations.loader import MigrationLoader

from posthog.models.organization import Organization
from posthog.models.team.util import delete_team_records

pytestmark = [pytest.mark.django_db]

RETIRED_INTERVIEW_MODELS = ("UserInterview", "IntervieweeContext", "UserInterviewTopic")


def test_deleting_a_team_deletes_its_retired_user_interviews():
    apps = (
        MigrationLoader(connection)
        .project_state([("user_interviews", "0010_alter_intervieweecontext_team_and_more")])
        .apps
    )
    _, _, team = Organization.objects.bootstrap(None)
    _, _, other_team = Organization.objects.bootstrap(None)
    for team_id in (team.id, other_team.id):
        topic = apps.get_model("user_interviews", "UserInterviewTopic").objects.create(
            team_id=team_id, topic="Onboarding"
        )
        apps.get_model("user_interviews", "IntervieweeContext").objects.create(
            team_id=team_id, topic=topic, interviewee_identifier="person@example.com", agent_context="context"
        )
        apps.get_model("user_interviews", "UserInterview").objects.create(
            team_id=team_id, interviewee_emails=["person@example.com"], transcript="transcript"
        )

    delete_team_records([team.id])

    for model_name in RETIRED_INTERVIEW_MODELS:
        rows = apps.get_model("user_interviews", model_name).objects
        assert not rows.filter(team_id=team.id).exists(), model_name
        assert rows.filter(team_id=other_team.id).exists(), model_name
