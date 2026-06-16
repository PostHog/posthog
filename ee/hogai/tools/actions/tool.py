from typing import Literal, Optional

from pydantic import BaseModel

from posthog.sync import database_sync_to_async

from products.actions.backend.models.action import Action

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

from .core import (
    ActionStepInput,
    ActionToolError,
    CreateActionToolArgs,
    DeleteActionToolArgs,
    GetActionToolArgs,
    ListActionsToolArgs,
    UpdateActionToolArgs,
    create_action,
    delete_action,
    get_action,
    get_action_object,
    list_actions,
    update_action,
)


async def _fetch_action(tool: MaxTool, action_id: int) -> Action:
    """Fetch an action for a tool's team, mapping a missing action to a retryable error."""
    try:
        return await database_sync_to_async(get_action_object)(tool._team, action_id)
    except ActionToolError as e:
        raise MaxToolRetryableError(str(e))


LIST_ACTIONS_DESCRIPTION = """
List the project's actions (reusable event definitions used in insights and funnels).

Projects can have thousands of actions, so this tool is paginated and capped — always pass `search` when you're
looking for a specific action by name, and use `limit`/`offset` to page rather than trying to fetch everything.
Use this to discover an action's ID before reading its properties (read_taxonomy), updating, or deleting it.
""".strip()

GET_ACTION_DESCRIPTION = "Get a single action by ID, including its full step (trigger condition) definition.".strip()

CREATE_ACTION_DESCRIPTION = """
Create a new action. An action unifies one or more trigger conditions ("steps", OR-ed together) into a single
reusable event — e.g. a "Signup" action matching a $pageview on /signup OR an $autocapture click on a button.
Steps can match by event name, URL, CSS selector, element text/tag, href, and property filters.
""".strip()

UPDATE_ACTION_DESCRIPTION = """
Update an existing action's name, description, or steps. Providing `steps` REPLACES all existing steps, so include
the full desired set. Look up the current definition with get_action first if you only want to tweak part of it.
""".strip()

DELETE_ACTION_DESCRIPTION = "Delete an action by ID. This removes it from insights and funnels that use it.".strip()


class ListActionsTool(MaxTool):
    name: Literal["list_actions"] = "list_actions"
    description: str = LIST_ACTIONS_DESCRIPTION
    args_schema: type[BaseModel] = ListActionsToolArgs

    def get_required_resource_access(self):
        return [("action", "viewer")]

    async def _arun_impl(
        self, search: Optional[str] = None, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> tuple[str, None]:
        result = await database_sync_to_async(list_actions)(self._team, search, limit, offset)
        return result, None


class GetActionTool(MaxTool):
    name: Literal["get_action"] = "get_action"
    description: str = GET_ACTION_DESCRIPTION
    args_schema: type[BaseModel] = GetActionToolArgs

    def get_required_resource_access(self):
        return [("action", "viewer")]

    async def _arun_impl(self, action_id: int) -> tuple[str, None]:
        action = await _fetch_action(self, action_id)
        await self.check_object_access(action, "viewer", action="read")
        return await database_sync_to_async(get_action)(self._team, action_id), None


class CreateActionTool(MaxTool):
    name: Literal["create_action"] = "create_action"
    description: str = CREATE_ACTION_DESCRIPTION
    args_schema: type[BaseModel] = CreateActionToolArgs

    def get_required_resource_access(self):
        return [("action", "editor")]

    async def _arun_impl(
        self, name: str, description: Optional[str] = None, steps: Optional[list[ActionStepInput]] = None
    ) -> tuple[str, None]:
        try:
            result = await database_sync_to_async(create_action)(self._team, self._user, name, description, steps)
        except ActionToolError as e:
            raise MaxToolRetryableError(str(e))
        return result, None


class UpdateActionTool(MaxTool):
    name: Literal["update_action"] = "update_action"
    description: str = UPDATE_ACTION_DESCRIPTION
    args_schema: type[BaseModel] = UpdateActionToolArgs

    def get_required_resource_access(self):
        return [("action", "editor")]

    async def _arun_impl(
        self,
        action_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        steps: Optional[list[ActionStepInput]] = None,
    ) -> tuple[str, None]:
        action = await _fetch_action(self, action_id)
        await self.check_object_access(action, "editor", action="edit")
        try:
            result = await database_sync_to_async(update_action)(
                self._team, self._user, action_id, name, description, steps
            )
        except ActionToolError as e:
            raise MaxToolRetryableError(str(e))
        return result, None


class DeleteActionTool(MaxTool):
    name: Literal["delete_action"] = "delete_action"
    description: str = DELETE_ACTION_DESCRIPTION
    args_schema: type[BaseModel] = DeleteActionToolArgs

    def get_required_resource_access(self):
        return [("action", "editor")]

    async def is_dangerous_operation(self, action_id: int) -> bool:
        return True

    async def format_dangerous_operation_preview(self, action_id: int) -> str:
        action = await _fetch_action(self, action_id)
        await self.check_object_access(action, "editor", action="delete")
        current = await database_sync_to_async(get_action)(self._team, action_id)
        return f"Delete this action — it will be removed from any insights and funnels that use it:\n{current}"

    async def _arun_impl(self, action_id: int) -> tuple[str, None]:
        action = await _fetch_action(self, action_id)
        await self.check_object_access(action, "editor", action="delete")
        try:
            result = await database_sync_to_async(delete_action)(self._team, self._user, action_id)
        except ActionToolError as e:
            raise MaxToolRetryableError(str(e))
        return result, None
