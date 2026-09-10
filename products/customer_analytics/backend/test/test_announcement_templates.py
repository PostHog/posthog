from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.customer_analytics.backend.models import AnnouncementTemplate


class TestAnnouncementTemplateAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/announcement_templates/"

    def _create(self, name="Onboarding nudge", message="Welcome aboard!"):
        return self.client.post(self.base_url, {"name": name, "message": message}, format="json")

    def test_create_persists_template_and_returns_it(self):
        response = self._create()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["name"] == "Onboarding nudge"
        assert data["message"] == "Welcome aboard!"
        assert data["created_by"]["id"] == self.user.pk
        template = AnnouncementTemplate.all_teams.get(id=data["id"])
        assert template.team_id == self.team.pk
        assert template.deleted is False

    def test_create_rejects_blank_name_and_message(self):
        assert self._create(name="   ").status_code == status.HTTP_400_BAD_REQUEST
        assert self._create(message="   ").status_code == status.HTTP_400_BAD_REQUEST

    def test_create_rejects_duplicate_name(self):
        assert self._create(name="Renewal reminder").status_code == status.HTTP_201_CREATED
        dup = self._create(name="Renewal reminder", message="different body")
        assert dup.status_code == status.HTTP_400_BAD_REQUEST
        assert "name" in dup.json()

    def test_list_returns_only_live_templates_ordered_by_name(self):
        self._create(name="Bravo")
        self._create(name="Alpha")
        deleted = self._create(name="Zeta")
        self.client.delete(f"{self.base_url}{deleted.json()['id']}/")

        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK
        names = [row["name"] for row in response.json()["results"]]
        assert names == ["Alpha", "Bravo"]

    def test_retrieve_returns_template(self):
        created = self._create().json()
        response = self.client.get(f"{self.base_url}{created['id']}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == created["id"]

    def test_update_changes_name_and_message(self):
        created = self._create().json()
        response = self.client.put(
            f"{self.base_url}{created['id']}/",
            {"name": "Renamed", "message": "New body"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["name"] == "Renamed"
        assert response.json()["message"] == "New body"

    def test_update_rejects_name_used_by_another_live_template(self):
        self._create(name="Taken")
        target = self._create(name="Free").json()
        response = self.client.put(
            f"{self.base_url}{target['id']}/",
            {"name": "Taken", "message": "body"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_soft_deletes_and_frees_the_name(self):
        created = self._create(name="OOO").json()
        response = self.client.delete(f"{self.base_url}{created['id']}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        template = AnnouncementTemplate.all_teams.get(id=created["id"])
        assert template.deleted is True
        assert self.client.get(f"{self.base_url}{created['id']}/").status_code == status.HTTP_404_NOT_FOUND
        # The name is reusable once the old template is soft-deleted.
        assert self._create(name="OOO").status_code == status.HTTP_201_CREATED

    def test_retrieve_with_malformed_id_returns_404(self):
        assert self.client.get(f"{self.base_url}not-a-uuid/").status_code == status.HTTP_404_NOT_FOUND

    def test_templates_are_isolated_per_team(self):
        other_team = Team.objects.create(
            organization=Organization.objects.create(name="Other org"), name="Other team"
        )
        other = AnnouncementTemplate.all_teams.create(team=other_team, name="Theirs", message="secret")

        assert self.client.get(self.base_url).json()["results"] == []
        assert self.client.get(f"{self.base_url}{other.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.delete(f"{self.base_url}{other.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert AnnouncementTemplate.all_teams.get(id=other.id).deleted is False
