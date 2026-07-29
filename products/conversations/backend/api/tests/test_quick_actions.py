from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.conversations.backend.models import QuickAction, Ticket
from products.workflows.backend.facade.api import HogFlowNotRunnableError, HogFlowServiceError


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
            patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=True),
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
        # access to the workflow execute it. The runner's access is checked, not the creator's.
        workflow_qa = self._create_workflow_quick_action("01890000-0000-0000-0000-000000000004")
        ticket = Ticket.objects.create_with_number(team=self.team, widget_session_id="s2", distinct_id="d2")

        self.client.force_login(self.other_user)
        with (
            patch("products.conversations.backend.api.quick_actions.invoke_hog_flow_now") as invoke,
            patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=True),
            patch("products.conversations.backend.api.quick_actions.user_can_run_workflow", return_value=False),
        ):
            denied = self.client.post(
                f"{self.base_url}{workflow_qa['short_id']}/run/", {"ticket_id": str(ticket.id)}, format="json"
            )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN, denied.content)
        invoke.assert_not_called()

    def test_run_maps_service_failure_to_502_but_invalid_workflow_to_400(self) -> None:
        # Regression guard: a workflow-service HTTP failure (e.g. the manual-invocation route not
        # deployed yet, a 404 requests won't raise on) must surface as a 502, while a genuinely
        # non-runnable workflow stays a 400. The two must not be conflated.
        workflow_qa = self._create_workflow_quick_action("01890000-0000-0000-0000-000000000005")
        ticket = Ticket.objects.create_with_number(team=self.team, widget_session_id="s3", distinct_id="d3")

        for error, expected_status in [
            (HogFlowServiceError("Workflow run was rejected (404)."), status.HTTP_502_BAD_GATEWAY),
            (HogFlowNotRunnableError("That workflow does not exist or is not active."), status.HTTP_400_BAD_REQUEST),
        ]:
            with (
                patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=True),
                patch("products.conversations.backend.api.quick_actions.user_can_run_workflow", return_value=True),
                patch("products.conversations.backend.api.quick_actions.invoke_hog_flow_now", side_effect=error),
            ):
                response = self.client.post(
                    f"{self.base_url}{workflow_qa['short_id']}/run/", {"ticket_id": str(ticket.id)}, format="json"
                )
            self.assertEqual(response.status_code, expected_status, response.content)

    def test_run_rejects_workflow_not_runnable_in_current_environment(self) -> None:
        # Regression guard: a shared quick action whose workflow isn't active in this environment must
        # fail with a clear message before the RBAC check, not the misleading "no access" error.
        workflow_qa = self._create_workflow_quick_action("01890000-0000-0000-0000-000000000006")
        ticket = Ticket.objects.create_with_number(team=self.team, widget_session_id="s4", distinct_id="d4")

        with (
            patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=False),
            patch("products.conversations.backend.api.quick_actions.invoke_hog_flow_now") as invoke,
        ):
            response = self.client.post(
                f"{self.base_url}{workflow_qa['short_id']}/run/", {"ticket_id": str(ticket.id)}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        invoke.assert_not_called()

    @parameterized.expand(
        [
            ("ticket_scope_only_forbidden", ["ticket:write"], status.HTTP_403_FORBIDDEN),
            ("both_scopes_allowed", ["ticket:write", "hog_flow:write"], status.HTTP_202_ACCEPTED),
        ]
    )
    def test_run_via_api_key_requires_workflow_write_scope(
        self, _name: str, scopes: list[str], expected_status: int
    ) -> None:
        # Security regression guard: running a workflow executes its stored-secret actions, so a
        # ticket:write-only personal API key must not be able to trigger workflow execution.
        workflow_qa = self._create_workflow_quick_action("01890000-0000-0000-0000-000000000002")
        ticket = Ticket.objects.create_with_number(team=self.team, widget_session_id="s1", distinct_id="d1")
        client = self._bearer_client(scopes)
        with (
            patch("products.conversations.backend.api.quick_actions.invoke_hog_flow_now"),
            patch("products.conversations.backend.api.quick_actions.workflow_is_runnable", return_value=True),
            patch("products.conversations.backend.api.quick_actions.user_can_run_workflow", return_value=True),
        ):
            response = client.post(
                f"{self.base_url}{workflow_qa['short_id']}/run/", {"ticket_id": str(ticket.id)}, format="json"
            )
        self.assertEqual(response.status_code, expected_status, response.content)

    def test_unrelated_edit_not_blocked_when_workflow_became_inactive(self) -> None:
        # Regression guard: once a workflow is attached, an unrelated edit (rename) must not be
        # rejected just because the workflow was archived afterward. The active-workflow check
        # applies only when the workflow reference itself is being set or changed.
        created = self._create_workflow_quick_action("01890000-0000-0000-0000-000000000007")
        runnable, can_run = self._allow_workflow(runnable=False)
        with runnable, can_run:
            renamed = self.client.patch(f"{self.base_url}{created['short_id']}/", {"name": "Renamed"}, format="json")
        self.assertEqual(renamed.status_code, status.HTTP_200_OK, renamed.content)

    @parameterized.expand(
        [
            ("unchanged_workflow_id_resent", "01890000-0000-0000-0000-000000000007", status.HTTP_200_OK),
            ("changed_to_archived_workflow", "01890000-0000-0000-0000-000000000008", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_resent_workflow_id_only_revalidated_when_changed(
        self, _name: str, patched_workflow_id: str, expected_status: int
    ) -> None:
        # Regression guard: the settings UI resends workflow_id on every save, so a rename carrying
        # the unchanged id must not be rejected after the workflow was archived, while actually
        # switching to an archived workflow must still be rejected.
        created = self._create_workflow_quick_action("01890000-0000-0000-0000-000000000007")
        runnable, can_run = self._allow_workflow(runnable=False)
        with runnable, can_run:
            response = self.client.patch(
                f"{self.base_url}{created['short_id']}/",
                {"name": "Renamed", "workflow_id": patched_workflow_id},
                format="json",
            )
        self.assertEqual(response.status_code, expected_status, response.content)
        if expected_status == status.HTTP_200_OK:
            self.assertEqual(QuickAction.objects.unscoped().get(short_id=created["short_id"]).name, "Renamed")

    def _bearer_client(self, scopes: list[str]) -> APIClient:
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="qa-key", user=self.user, secure_value=hash_key_value(raw), scopes=scopes)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        return client

    @parameterized.expand(
        [
            (
                "attach_denied_without_workflow_scope",
                ["ticket:write"],
                "patch",
                {"workflow_id": "01890000-0000-0000-0000-000000000009"},
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "rename_allowed_without_workflow_scope",
                ["ticket:write"],
                "patch",
                {"name": "Renamed"},
                status.HTTP_200_OK,
            ),
            (
                "unchanged_workflow_id_allowed_without_workflow_scope",
                ["ticket:write"],
                "patch",
                {"name": "Renamed", "workflow_id": "01890000-0000-0000-0000-000000000007"},
                status.HTTP_200_OK,
            ),
            (
                "attach_allowed_with_workflow_scope",
                ["ticket:write", "hog_flow:write"],
                "patch",
                {"workflow_id": "01890000-0000-0000-0000-000000000009"},
                status.HTTP_200_OK,
            ),
            (
                "create_denied_without_workflow_scope",
                ["ticket:write"],
                "post",
                {"name": "New", "workflow_id": "01890000-0000-0000-0000-000000000009"},
                status.HTTP_403_FORBIDDEN,
            ),
        ]
    )
    def test_setting_workflow_via_api_key_requires_workflow_scope(
        self, _name: str, scopes: list[str], method: str, body: dict, expected_status: int
    ) -> None:
        # Security regression guard: attaching a workflow arms an automation other agents can then
        # trigger, so a ticket:write-only personal API key must not set or change workflow_id
        # (mirroring the explicit scopes on the run action). Edits that leave the workflow
        # reference alone must stay possible with ticket:write.
        created = self._create_workflow_quick_action("01890000-0000-0000-0000-000000000007")
        client = self._bearer_client(scopes)
        runnable, can_run = self._allow_workflow()
        with runnable, can_run:
            if method == "post":
                response = client.post(self.base_url, body, format="json")
            else:
                response = client.patch(f"{self.base_url}{created['short_id']}/", body, format="json")
        self.assertEqual(response.status_code, expected_status, response.content)

    def test_quick_actions_visible_from_child_environment(self) -> None:
        # Regression guard: quick actions are stored under the canonical parent team, so a child
        # environment must still list them. If the parent-lookup filter re-ANDs the raw child team
        # id, list/retrieve return nothing and the feature is dead for multi-environment projects.
        child_team = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="Child environment"
        )
        child_url = f"/api/projects/{child_team.id}/conversations/quick_actions/"
        created = self.client.post(child_url, {"name": "From child", "content": "Hi"}, format="json").json()

        listed = {q["short_id"] for q in self.client.get(child_url).json()["results"]}
        self.assertIn(created["short_id"], listed)
        self.assertEqual(self.client.get(f"{child_url}{created['short_id']}/").status_code, status.HTTP_200_OK)

    @parameterized.expand(["get", "patch", "delete"])
    def test_other_teams_quick_action_is_not_reachable_object_level(self, method: str) -> None:
        # Regression guard: list scoping is covered above, but retrieve/update/delete resolve a
        # single object by short_id and must 404 across teams too, or the id becomes an IDOR.
        created = self._create("Team-scoped reply")
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        url = f"/api/projects/{other_team.id}/conversations/quick_actions/{created['short_id']}/"
        if method == "patch":
            response = self.client.patch(url, {"name": "Hijacked"}, format="json")
        else:
            response = getattr(self.client, method)(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)
        quick_action = QuickAction.objects.unscoped().get(short_id=created["short_id"])
        self.assertEqual(quick_action.name, "Team-scoped reply")

    def test_assignee_only_action_can_be_resaved_after_clearing_reply(self) -> None:
        # Regression guard: an assignee-only quick action (assignee is API-only) still counts as
        # doing something. Clearing the reply and submitting empty actions from the UI must not be
        # rejected as empty, so validate() has to see the assignee that update() merges back.
        created = self.client.post(
            self.base_url,
            {"name": "Route to on-call", "actions": {"assignee": {"type": "user", "id": "42"}}},
            format="json",
        ).json()
        response = self.client.patch(
            f"{self.base_url}{created['short_id']}/", {"content": "", "actions": {}}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        quick_action = QuickAction.objects.unscoped().get(short_id=created["short_id"])
        self.assertEqual(quick_action.actions, {"assignee": {"type": "user", "id": "42"}})
