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

    def _create(self, name: str, visibility: str = "team", **extra: object) -> dict:
        body = {"name": name, "visibility": visibility, "content": "Hi {{customer.name}}", **extra}
        response = self.client.post(self.base_url, body, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        return response.json()

    def test_create_sets_team_and_creator(self) -> None:
        created = self._create("Reproduction steps")
        quick_action = QuickAction.objects.unscoped().get(short_id=created["short_id"])
        self.assertEqual(quick_action.team_id, self.team.id)
        self.assertEqual(quick_action.created_by_id, self.user.id)

    def test_quick_action_must_do_something(self) -> None:
        # Regression guard: a quick action with no reply, no ticket actions, and no workflow is
        # useless and must be rejected.
        response = self.client.post(self.base_url, {"name": "Empty"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

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

    def _allow_workflow(self, runnable: bool = True, can_run: bool = True):
        """Patch the two workflow-facade checks the quick-action API consults."""
        return (
            patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=runnable),
            patch("products.conversations.backend.api.quick_actions.user_can_run_workflow", return_value=can_run),
        )

    def test_workflow_must_be_runnable(self) -> None:
        # A quick action that runs a workflow must reference an active workflow.
        workflow_id = "01890000-0000-0000-0000-000000000001"
        runnable, can_run = self._allow_workflow(runnable=False)
        with runnable, can_run:
            rejected = self.client.post(
                self.base_url,
                {"name": "Escalate", "workflow_id": workflow_id},
                format="json",
            )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST, rejected.content)

        runnable, can_run = self._allow_workflow()
        with runnable, can_run:
            created = self.client.post(
                self.base_url,
                {"name": "Escalate", "workflow_id": workflow_id},
                format="json",
            )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content)

    def test_attaching_workflow_requires_access(self) -> None:
        # Security regression guard: a user without RBAC access to a workflow must not be able to
        # attach it to a quick action by UUID.
        runnable, can_run = self._allow_workflow(can_run=False)
        with runnable, can_run:
            rejected = self.client.post(
                self.base_url,
                {"name": "Escalate", "workflow_id": "01890000-0000-0000-0000-000000000009"},
                format="json",
            )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST, rejected.content)

    def test_reply_and_workflow_combine(self) -> None:
        # Regression guard: a quick action can carry both a reply and a workflow at once.
        workflow_id = "01890000-0000-0000-0000-000000000003"
        runnable, can_run = self._allow_workflow()
        with runnable, can_run:
            created = self.client.post(
                self.base_url,
                {"name": "Reply + run", "content": "Generating that for you", "workflow_id": workflow_id},
                format="json",
            )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.content)
        quick_action = QuickAction.objects.unscoped().get(short_id=created.json()["short_id"])
        self.assertEqual(quick_action.content, "Generating that for you")
        self.assertEqual(str(quick_action.workflow_id), workflow_id)

    def _create_workflow_quick_action(self, workflow_id: str) -> dict:
        runnable, can_run = self._allow_workflow()
        with runnable, can_run:
            return self.client.post(
                self.base_url,
                {"name": "Escalate", "workflow_id": workflow_id},
                format="json",
            ).json()

    def test_run_invokes_workflow_against_ticket(self) -> None:
        # Regression guard: the run endpoint must invoke the workflow with globals carrying the
        # ticket id, and reject quick actions that have no workflow.
        workflow_id = "01890000-0000-0000-0000-000000000002"
        workflow_qa = self._create_workflow_quick_action(workflow_id)
        response_qa = self._create("Canned reply")
        ticket = Ticket.objects.create_with_number(team=self.team, widget_session_id="s1", distinct_id="d1")

        with (
            patch("products.conversations.backend.api.quick_actions.invoke_hog_flow_now") as invoke,
            patch("products.conversations.backend.api.quick_actions.user_can_run_workflow", return_value=True),
        ):
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

    def test_run_requires_workflow_access_for_the_runner(self) -> None:
        # Security regression guard: a shared quick action must not let a runner without RBAC
        # access to the workflow execute it — the runner's access is checked, not the creator's.
        workflow_qa = self._create_workflow_quick_action("01890000-0000-0000-0000-000000000004")
        ticket = Ticket.objects.create_with_number(team=self.team, widget_session_id="s2", distinct_id="d2")

        self.client.force_login(self.other_user)
        with (
            patch("products.conversations.backend.api.quick_actions.invoke_hog_flow_now") as invoke,
            patch("products.conversations.backend.api.quick_actions.user_can_run_workflow", return_value=False),
        ):
            denied = self.client.post(
                f"{self.base_url}{workflow_qa['short_id']}/run/", {"ticket_id": str(ticket.id)}, format="json"
            )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN, denied.content)
        invoke.assert_not_called()
