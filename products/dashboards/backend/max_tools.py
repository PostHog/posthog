from django.db import transaction

import structlog
from pydantic import BaseModel, Field

from posthog.schema import AssistantToolCallMessage

from posthog.exceptions_capture import capture_exception
from posthog.models import Dashboard
from posthog.sync import database_sync_to_async

from ee.hogai.graph.dashboards.nodes import DashboardCreationNode
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantState, InsightQuery

logger = structlog.get_logger(__name__)


class EditCurrentDashboardArgs(BaseModel):
    """
    Edits the dashboard the user is currently working on by modifying its properties or the insights it contains.
    """

    dashboard_name: str = Field(
        description="The new name for the dashboard. Only provide if the user explicitly asks to rename the dashboard.",
    )
    insights_to_add: list[InsightQuery] = Field(
        description="List of insights to add to the dashboard. Each insight should include a name and description. Only provide if the user explicitly asks to add insights.",
    )


class EditCurrentDashboardTool(MaxTool):
    name: str = "edit_current_dashboard"
    description: str = "Update the dashboard the user is currently working on, such as renaming it or adding insights."
    thinking_message: str = "Editing your dashboard"
    root_system_prompt_template: str = """The user is currently editing a dashboard. Here is that dashboard's current definition:

```json
{current_dashboard}
```

You can edit this dashboard using the `edit_current_dashboard` tool to rename it or add insights to it.
IMPORTANT: When adding insights, you must provide a complete description of what the insight should show.
""".strip()

    args_schema: type[BaseModel] = EditCurrentDashboardArgs
    show_tool_call_message: bool = False

    async def _arun_impl(
        self, dashboard_name: str | None = None, insights_to_add: list[InsightQuery] | None = None
    ) -> tuple[str, None]:
        if "current_dashboard" not in self.context:
            raise ValueError("Context `current_dashboard` is required for the `edit_current_dashboard` tool")

        dashboard_id = self.context["current_dashboard"].get("id")
        if not dashboard_id:
            raise ValueError("Dashboard ID not found in context")

        state = self._state
        result_message = ""
        if dashboard_name:
            result_message += await self._handle_dashboard_name_update(dashboard_id, dashboard_name)

        if insights_to_add:
            state.search_insights_queries = insights_to_add
            state.dashboard_id = dashboard_id
            result_message += await self._handle_insights_addition(state, insights_to_add)

        return result_message, None

    @database_sync_to_async
    @transaction.atomic
    def _update_dashboard_name(self, dashboard_id: int, new_name: str) -> Dashboard:
        """Update the dashboard name."""
        dashboard = Dashboard.objects.get(id=dashboard_id, team=self._team)
        dashboard.name = new_name
        dashboard.save(update_fields=["name"])
        return dashboard

    async def _handle_dashboard_name_update(self, dashboard_id: int, new_name: str) -> str:
        result_message = ""
        try:
            await self._update_dashboard_name(dashboard_id, new_name)
        except Exception as e:
            logger.warning("Failed to rename the dashboard.", extra={"error": e})
            capture_exception(e)
            result_message += f"Dashboard was not renamed to {new_name}."
        else:
            result_message += f"Dashboard was renamed to {new_name} successfully."

        return result_message

    async def _handle_insights_addition(self, state: AssistantState, insights_to_add: list[InsightQuery]) -> str:
        result_message = ""
        try:
            dashboard_creation_node = DashboardCreationNode(self._team, self._user)
            result = await dashboard_creation_node.arun(state, self._config)

            result_message += (
                result.messages[0].content
                if result.messages and isinstance(result.messages[0], AssistantToolCallMessage)
                else f"Dashboard was edited successfully. Added {len(insights_to_add)} insights to the dashboard."
            )
        except Exception as e:
            logger.warning("Failed to add the insights to the dashboard.", extra={"error": e})
            capture_exception(e)
            result_message += f"Failed to add the insights to the dashboard."
        return result_message
