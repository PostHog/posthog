from posthog.test.base import APIBaseTest

from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.models import AgentSignature


class TestAgentSignatureAPI(APIBaseTest):
    def _url(self, team: Team | None = None) -> str:
        return f"/api/projects/{(team or self.team).id}/conversations/my_signature/"

    def test_signature_is_personal_to_each_user_and_project(self) -> None:
        response = self.client.post(self._url(), {"text": "  Ann\nSupport lead  ", "include_profile_picture": False})
        assert response.status_code == 200, response.json()
        assert response.json() == {"text": "Ann\nSupport lead", "include_profile_picture": False}
        assert self.client.get(self._url()).json() == {"text": "Ann\nSupport lead", "include_profile_picture": False}

        other_user = User.objects.create_and_join(self.organization, "other@example.com", "password")
        self.client.force_login(other_user)
        assert self.client.get(self._url()).json() == {"text": "", "include_profile_picture": True}
        self.client.post(self._url(), {"text": "Bo", "include_profile_picture": True})

        self.client.force_login(self.user)
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        assert self.client.get(self._url(other_team)).json() == {"text": "", "include_profile_picture": True}
        assert AgentSignature.objects.for_team(self.team.id).get(user=self.user).text == "Ann\nSupport lead"
        assert AgentSignature.objects.for_team(self.team.id).get(user=other_user).text == "Bo"

    def test_signature_rejects_text_over_the_limit(self) -> None:
        response = self.client.post(self._url(), {"text": "x" * 1001, "include_profile_picture": True})
        assert response.status_code == 400
        assert not AgentSignature.objects.for_team(self.team.id).exists()
