from uuid import uuid4

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Project, Team, User

from products.ai_observability.backend.models.parser_recipe import ParserRecipe

VALID_SOURCE = "id: my_recipe\nrules: []\n"


class TestParserRecipesApi(APIBaseTest):
    def _endpoint(self) -> str:
        return f"/api/projects/{self.team.id}/llm_analytics/parser_recipes/"

    def test_non_admin_member_can_write(self):
        # Managing recipes is intentionally not admin-only — a plain member can create.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self._endpoint(), {"name": "Member recipe", "source": VALID_SOURCE})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_persists_recipe_and_sets_created_by(self):
        response = self.client.post(self._endpoint(), {"name": "My recipe", "source": VALID_SOURCE})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["name"], "My recipe")
        self.assertEqual(data["source"], VALID_SOURCE)
        self.assertEqual(data["created_by"]["id"], self.user.id)

        recipe = ParserRecipe.objects.for_team(self.team.id).get(id=data["id"])
        self.assertEqual(recipe.team_id, self.team.id)

    def test_create_rejects_source_that_is_not_yaml(self):
        response = self.client.post(self._endpoint(), {"name": "Broken", "source": "rules: [unclosed"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not valid YAML", response.json()["detail"])
        self.assertEqual(ParserRecipe.objects.for_team(self.team.id).count(), 0)

    def test_create_rejects_deeply_nested_source_with_400(self):
        # PyYAML raises RecursionError on this input — it must surface as a 400, not a 500
        response = self.client.post(self._endpoint(), {"name": "Deep", "source": "[" * 2000 + "]" * 2000})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ParserRecipe.objects.for_team(self.team.id).count(), 0)

    def test_create_rejects_oversized_source(self):
        response = self.client.post(self._endpoint(), {"name": "Big", "source": "# " + "x" * 100_001})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ParserRecipe.objects.for_team(self.team.id).count(), 0)

    def test_patch_rejects_source_that_is_not_yaml(self):
        recipe = ParserRecipe.objects.unscoped().create(team=self.team, name="ok", source=VALID_SOURCE)

        response = self.client.patch(f"{self._endpoint()}{recipe.id}/", {"source": "{{{"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        recipe.refresh_from_db()
        self.assertEqual(recipe.source, VALID_SOURCE)

    def test_list_returns_only_this_teams_recipes(self):
        ParserRecipe.objects.unscoped().create(team=self.team, name="mine", source=VALID_SOURCE)
        other_team = self._other_team()
        ParserRecipe.objects.unscoped().create(team=other_team, name="theirs", source=VALID_SOURCE)

        response = self.client.get(self._endpoint())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in response.json()["results"]]
        self.assertEqual(names, ["mine"])

    def test_cannot_retrieve_another_teams_recipe(self):
        other_team = self._other_team()
        other_recipe = ParserRecipe.objects.unscoped().create(team=other_team, name="theirs", source=VALID_SOURCE)

        response = self.client.get(f"{self._endpoint()}{other_recipe.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_updates_name_and_source(self):
        recipe = ParserRecipe.objects.unscoped().create(team=self.team, name="old", source=VALID_SOURCE)
        new_source = "id: changed\nrules: []\n"

        response = self.client.patch(
            f"{self._endpoint()}{recipe.id}/", {"name": "new", "source": new_source}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        recipe.refresh_from_db()
        self.assertEqual(recipe.name, "new")
        self.assertEqual(recipe.source, new_source)

    def test_delete_removes_recipe(self):
        recipe = ParserRecipe.objects.unscoped().create(team=self.team, name="doomed", source=VALID_SOURCE)

        response = self.client.delete(f"{self._endpoint()}{recipe.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ParserRecipe.objects.for_team(self.team.id).filter(id=recipe.id).exists())

    def _other_team(self) -> Team:
        org = Organization.objects.create(name="other")
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
        team = Team.objects.create(id=project.id, project=project, organization=org, api_token=str(uuid4()))
        User.objects.create_and_join(org, "other-parser-recipes@posthog.com", "testpassword123")
        return team
