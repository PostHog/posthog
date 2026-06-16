import uuid

from posthog.test.base import NonAtomicBaseTest

from parameterized import parameterized

from posthog.models import Project, Team

from products.actions.backend.models.action import Action

from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.tools.actions.core import MAX_LIST_LIMIT, ActionStepInput
from ee.hogai.tools.actions.tool import (
    CreateActionTool,
    DeleteActionTool,
    GetActionTool,
    ListActionsTool,
    UpdateActionTool,
)


class TestActionTools(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        for name in ["Checkout started", "Checkout completed", "Signup", "Pricing viewed"]:
            Action.objects.create(team=self.team, name=name, created_by=self.user)

        # A separate team in the same org, with its own action, to assert isolation.
        foreign_project = Project.objects.create(
            id=Team.objects.increment_id_sequence(), organization=self.organization
        )
        foreign_team = Team.objects.create(
            id=foreign_project.id,
            project=foreign_project,
            organization=self.organization,
            api_token=str(uuid.uuid4()),
        )
        self.foreign_action = Action.objects.create(team=foreign_team, name="Foreign action", created_by=self.user)

    def _list_tool(self):
        return ListActionsTool(team=self.team, user=self.user)

    async def test_list_returns_all_by_default(self):
        content, _ = await self._list_tool()._arun_impl()
        self.assertIn("Showing 4 of 4", content)
        self.assertIn("Checkout started", content)

    async def test_list_search_is_case_insensitive(self):
        content, _ = await self._list_tool()._arun_impl(search="checkout")
        self.assertIn("Showing 2 of 2", content)
        self.assertIn("Checkout started", content)
        self.assertIn("Checkout completed", content)
        self.assertNotIn("Signup", content)

    async def test_list_search_no_match(self):
        content, _ = await self._list_tool()._arun_impl(search="nonexistent")
        self.assertIn("No actions found", content)

    async def test_list_limit_caps_results(self):
        content, _ = await self._list_tool()._arun_impl(limit=2)
        self.assertIn("Showing 2 of 4", content)

    async def test_list_offset_paginates_without_overlap(self):
        page1, _ = await self._list_tool()._arun_impl(limit=2, offset=0)
        page2, _ = await self._list_tool()._arun_impl(limit=2, offset=2)
        # Ordered by name; pages must be disjoint.
        self.assertIn("Checkout completed", page1)
        self.assertIn("Checkout started", page1)
        self.assertIn("Pricing viewed", page2)
        self.assertIn("Signup", page2)

    async def test_list_limit_is_hard_capped(self):
        # Seed beyond the cap (setUp already created 4) and confirm a huge limit still clamps.
        await Action.objects.abulk_create(
            [Action(team=self.team, name=f"Bulk {i:04d}", created_by=self.user) for i in range(MAX_LIST_LIMIT + 5)]
        )
        content, _ = await self._list_tool()._arun_impl(limit=10_000)
        self.assertIn(f"Showing {MAX_LIST_LIMIT} of {MAX_LIST_LIMIT + 9}", content)

    async def test_list_offset_beyond_total_explains_offset(self):
        content, _ = await self._list_tool()._arun_impl(offset=100)
        self.assertIn("offset 100", content)
        self.assertIn("lower offset", content)

    async def test_create_action_with_step(self):
        content, _ = await CreateActionTool(team=self.team, user=self.user)._arun_impl(
            name="New action",
            description="desc",
            steps=[ActionStepInput(event="$pageview", url="/x", url_matching="contains")],
        )
        self.assertIn("Created action", content)
        action = await Action.objects.aget(team=self.team, name="New action")
        self.assertEqual(action.description, "desc")
        assert action.steps_json is not None
        self.assertEqual(len(action.steps_json), 1)
        step = action.steps_json[0]
        self.assertEqual(step["event"], "$pageview")
        self.assertEqual(step["url"], "/x")
        self.assertEqual(step["url_matching"], "contains")
        self.assertEqual(action.created_by_id, self.user.id)
        # Saving computes bytecode.
        self.assertIsNotNone(action.bytecode)

    @parameterized.expand([("blank", "   "), ("empty", "")])
    async def test_create_action_rejects_blank_name(self, _name: str, value: str):
        with self.assertRaises(MaxToolRetryableError):
            await CreateActionTool(team=self.team, user=self.user)._arun_impl(name=value)

    async def test_create_action_rejects_duplicate_name(self):
        with self.assertRaises(MaxToolRetryableError) as cm:
            await CreateActionTool(team=self.team, user=self.user)._arun_impl(name="Signup")
        self.assertIn("already has an action", str(cm.exception))

    async def test_get_action(self):
        action = await Action.objects.aget(team=self.team, name="Signup")
        content, _ = await GetActionTool(team=self.team, user=self.user)._arun_impl(action_id=action.id)
        self.assertIn(f"#{action.id} Signup", content)

    async def test_get_missing_action_is_retryable(self):
        with self.assertRaises(MaxToolRetryableError):
            await GetActionTool(team=self.team, user=self.user)._arun_impl(action_id=999_999)

    async def test_update_action_name_and_steps(self):
        action = await Action.objects.aget(team=self.team, name="Signup")
        await UpdateActionTool(team=self.team, user=self.user)._arun_impl(
            action_id=action.id,
            name="Signup renamed",
            steps=[ActionStepInput(event="signed_up")],
        )
        refreshed = await Action.objects.aget(pk=action.id)
        self.assertEqual(refreshed.name, "Signup renamed")
        assert refreshed.steps_json is not None
        self.assertEqual(len(refreshed.steps_json), 1)
        self.assertEqual(refreshed.steps_json[0]["event"], "signed_up")

    async def test_update_with_no_changes_is_noop(self):
        action = await Action.objects.aget(team=self.team, name="Signup")
        content, _ = await UpdateActionTool(team=self.team, user=self.user)._arun_impl(action_id=action.id)
        self.assertIn("Nothing to update", content)

    async def test_update_to_duplicate_name_is_rejected(self):
        action = await Action.objects.aget(team=self.team, name="Signup")
        with self.assertRaises(MaxToolRetryableError):
            await UpdateActionTool(team=self.team, user=self.user)._arun_impl(
                action_id=action.id, name="Checkout started"
            )

    async def test_delete_soft_deletes(self):
        action = await Action.objects.aget(team=self.team, name="Signup")
        content, _ = await DeleteActionTool(team=self.team, user=self.user)._arun_impl(action_id=action.id)
        self.assertIn("Deleted", content)
        refreshed = await Action.objects.aget(pk=action.id)
        self.assertTrue(refreshed.deleted)
        # Deleted actions are excluded from listing and lookups.
        with self.assertRaises(MaxToolRetryableError):
            await GetActionTool(team=self.team, user=self.user)._arun_impl(action_id=action.id)

    async def test_delete_is_marked_dangerous(self):
        action = await Action.objects.aget(team=self.team, name="Signup")
        tool = DeleteActionTool(team=self.team, user=self.user)
        self.assertTrue(await tool.is_dangerous_operation(action_id=action.id))
        preview = await tool.format_dangerous_operation_preview(action_id=action.id)
        self.assertIn("Signup", preview)

    async def test_team_isolation(self):
        # A tool scoped to self.team must not reach an action in another team.
        with self.assertRaises(MaxToolRetryableError):
            await GetActionTool(team=self.team, user=self.user)._arun_impl(action_id=self.foreign_action.id)
