from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import User

from products.conversations.backend.models import Macro


class TestMacroAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_user = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        self.base_url = f"/api/projects/{self.team.id}/conversations/macros/"

    def _create_macro(self, name: str, visibility: str = "team") -> dict:
        response = self.client.post(self.base_url, {"name": name, "visibility": visibility}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        return response.json()

    def test_create_sets_team_and_creator(self) -> None:
        created = self._create_macro("Reproduction steps")
        macro = Macro.objects.unscoped().get(short_id=created["short_id"])
        self.assertEqual(macro.team_id, self.team.id)
        self.assertEqual(macro.created_by_id, self.user.id)

    def test_visibility_scoping(self) -> None:
        # Regression guard: if safely_get_queryset drops the visibility filter, one agent's
        # personal macros leak to their teammates.
        team_macro = self._create_macro("Shared reply", visibility="team")
        my_personal = self._create_macro("My reply", visibility="personal")

        self.client.force_login(self.other_user)
        their_personal = self._create_macro("Their reply", visibility="personal")

        # Teammate sees the team macro and their own personal one, not mine.
        their_short_ids = {m["short_id"] for m in self.client.get(self.base_url).json()["results"]}
        self.assertIn(team_macro["short_id"], their_short_ids)
        self.assertIn(their_personal["short_id"], their_short_ids)
        self.assertNotIn(my_personal["short_id"], their_short_ids)

        # And I see the team macro and my own personal one, not theirs.
        self.client.force_login(self.user)
        my_short_ids = {m["short_id"] for m in self.client.get(self.base_url).json()["results"]}
        self.assertIn(team_macro["short_id"], my_short_ids)
        self.assertIn(my_personal["short_id"], my_short_ids)
        self.assertNotIn(their_personal["short_id"], my_short_ids)

    def test_actions_persist_only_known_keys(self) -> None:
        # Regression guard: the typed actions serializer must strip unknown keys. If `actions`
        # reverts to a bare JSONField, arbitrary keys would persist.
        response = self.client.post(
            self.base_url,
            {"name": "Close it", "actions": {"status": "resolved", "bogus": "should be dropped"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        macro = Macro.objects.unscoped().get(short_id=response.json()["short_id"])
        self.assertEqual(macro.actions, {"status": "resolved"})
