from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import User

from products.conversations.backend.models import QuickAction, Ticket


class TestQuickActionAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_user = User.objects.create_and_join(self.organization, "teammate@posthog.com", "password")
        self.base_url = f"/api/projects/{self.team.id}/conversations/quick_actions/"

    def _create(self, name: str, visibility: str = "team") -> dict:
        response = self.client.post(self.base_url, {"name": name, "visibility": visibility}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        return response.json()

    def test_create_sets_team_and_creator(self) -> None:
        created = self._create("Reproduction steps")
        quick_action = QuickAction.objects.unscoped().get(short_id=created["short_id"])
        self.assertEqual(quick_action.team_id, self.team.id)
        self.assertEqual(quick_action.created_by_id, self.user.id)
        self.assertEqual(quick_action.kind, "response")

    def test_visibility_scoping(self) -> None:
        # Regression guard: if safely_get_queryset drops the visibility filter, one agent's
        # personal quick actions leak to their teammates.
        team_qa = self._create("Shared reply", visibility="team")
        my_personal = self._create("My reply", visibility="personal")

        self.client.force_login(self.other_user)
        their_personal = self._create("Their reply", visibility="personal")

        their_ids = {q["short_id"] for q in self.client.get(self.base_url).json()["results"]}
        self.assertIn(team_qa["short_id"], their_ids)
        self.assertIn(their_personal["short_id"], their_ids)
        self.assertNotIn(my_personal["short_id"], their_ids)

        self.client.force_login(self.user)
        my_ids = {q["short_id"] for q in self.client.get(self.base_url).json()["results"]}
        self.assertIn(team_qa["short_id"], my_ids)
        self.assertIn(my_personal["short_id"], my_ids)
        self.assertNotIn(their_personal["short_id"], my_ids)

    def test_actions_persist_only_known_keys(self) -> None:
        # Regression guard: the typed actions serializer must strip unknown keys.
        response = self.client.post(
            self.base_url,
            {"name": "Close it", "actions": {"status": "resolved", "bogus": "should be dropped"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        quick_action = QuickAction.objects.unscoped().get(short_id=response.json()["short_id"])
        self.assertEqual(quick_action.actions, {"status": "resolved"})

    def test_non_creator_cannot_make_shared_personal(self) -> None:
        # Regression guard: flipping a shared team quick action personal as a non-creator would hide
        # it from everyone. The serializer must reject it.
        team_qa = self._create("Shared reply", visibility="team")

        self.client.force_login(self.other_user)
        response = self.client.patch(
            f"{self.base_url}{team_qa['short_id']}/", {"visibility": "personal"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(QuickAction.objects.unscoped().get(short_id=team_qa["short_id"]).visibility, "team")

        self.client.force_login(self.user)
        ok = self.client.patch(f"{self.base_url}{team_qa['short_id']}/", {"visibility": "personal"}, format="json")
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.content)

    def test_update_preserves_assignee_not_editable_in_ui(self) -> None:
        # Regression guard: the Settings UI can't edit `assignee`, so a partial update that omits it
        # must not wipe an assignee set via the API.
        created = self.client.post(
            self.base_url,
            {"name": "Route to on-call", "actions": {"assignee": {"type": "user", "id": "42"}}},
            format="json",
        ).json()
        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/", {"actions": {"status": "open"}}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        quick_action = QuickAction.objects.unscoped().get(short_id=created["short_id"])
        self.assertEqual(quick_action.actions, {"status": "open", "assignee": {"type": "user", "id": "42"}})

    def test_content_over_cap_is_rejected(self) -> None:
        response = self.client.post(self.base_url, {"name": "Too long", "content": "x" * 50_001}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    def test_workflow_kind_requires_a_runnable_workflow(self) -> None:
        # A workflow quick action must reference an active workflow; the serializer validates it.
        workflow_id = "01890000-0000-0000-0000-000000000001"
        with patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=False):
            rejected = self.client.post(
                self.base_url,
                {"name": "Escalate", "kind": "workflow", "workflow_id": workflow_id},
                format="json",
            )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST, rejected.content)

        with patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=True):
            created = self.client.post(
                self.base_url,
                {"name": "Escalate", "kind": "workflow", "workflow_id": workflow_id},
                format="json",
            )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content)

    def test_run_invokes_workflow_against_ticket(self) -> None:
        # Regression guard: the run endpoint must invoke the workflow with globals carrying the
        # ticket id, and reject non-workflow quick actions.
        workflow_id = "01890000-0000-0000-0000-000000000002"
        with patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=True):
            workflow_qa = self.client.post(
                self.base_url,
                {"name": "Escalate", "kind": "workflow", "workflow_id": workflow_id},
                format="json",
            ).json()
        response_qa = self._create("Canned reply")
        ticket = Ticket.objects.create_with_number(team=self.team, widget_session_id="s1", distinct_id="d1")

        with patch("products.conversations.backend.api.quick_actions.invoke_hog_flow_now") as invoke:
            ran = self.client.post(
                f"{self.base_url}{workflow_qa['short_id']}/run/", {"ticket_id": str(ticket.id)}, format="json"
            )
        self.assertEqual(ran.status_code, status.HTTP_202_ACCEPTED, ran.content)
        invoke.assert_called_once()
        team_id_arg, workflow_id_arg, globals_arg = invoke.call_args.args
        self.assertEqual(team_id_arg, self.team.id)
        self.assertEqual(str(workflow_id_arg), workflow_id)
        self.assertEqual(globals_arg["event"]["properties"]["ticket_id"], str(ticket.id))

        # A response quick action isn't runnable via this endpoint.
        with patch("products.conversations.backend.api.quick_actions.invoke_hog_flow_now") as invoke:
            bad = self.client.post(
                f"{self.base_url}{response_qa['short_id']}/run/", {"ticket_id": str(ticket.id)}, format="json"
            )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST, bad.content)
        invoke.assert_not_called()
