from typing import Any, Literal, Self

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from posthog.models import OrganizationMembership, Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.graph.sql.mixins import HogQLDatabaseMixin
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantState

READ_DATA_BILLING_PROMPT = """
# Billing information

Use this tool with the "billing_info" kind to retrieve the billing information if the user asks about billing, their subscription, their usage, or their spending.
You can use the information retrieved to check which PostHog products and add-ons the user has activated, how much they are spending, their usage history across all products in the last 30 days, as well as trials, spending limits, billing period, and more.
If the user wants to reduce their spending, always call this tool to get suggestions on how to do so.
If an insight shows zero data, it could mean either the query is looking at the wrong data or there was a temporary data collection issue. You can investigate potential dips in usage/captured data using the billing tool.
""".strip()

READ_DATA_PROMPT = f"""
Use this tool to read user data created in PostHog. This tool returns data that the user manually creates in PostHog.

# Data warehouse schema

Returns the SQL ClickHouse schema for the user's data warehouse.
You MUST use this tool when:
- Working with SQL.
- The request is about data warehouse, connected data sources, etc.

{{billing_prompt}}
""".strip()

BILLING_INSUFFICIENT_ACCESS_PROMPT = """
The user does not have admin access to view detailed billing information. They would need to contact an organization admin for billing details.
Suggest the user to contact the admins.
""".strip()

INVALID_KIND_PROMPT = """
<system_reminder>
Invalid kind. You must use "datawarehouse_schema" or "billing_info".
</system_reminder>
""".strip()

ReadDataKind = Literal["datawarehouse_schema"]
ReadDataAdminAccessKind = Literal["datawarehouse_schema", "billing_info"]


class ReadDataToolArgs(BaseModel):
    kind: ReadDataKind


class ReadDataAdminAccessToolArgs(BaseModel):
    kind: ReadDataAdminAccessKind


class ReadDataTool(HogQLDatabaseMixin, MaxTool):
    name: Literal["read_data"] = "read_data"
    description: str = READ_DATA_PROMPT
    thinking_message: str = "Reading your PostHog data"
    root_system_prompt_template: str = "Reads user data created in PostHog (data warehouse schema, billing information)"
    args_schema: type[BaseModel] = ReadDataToolArgs
    show_tool_call_message: bool = False

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
    ) -> Self:
        """
        Factory that creates a ReadDataTool with a dynamic args schema.

        Override this factory to add additional args schemas or descriptions.
        """
        args: type[BaseModel] = ReadDataToolArgs
        billing_prompt = ""
        if await cls._check_user_has_billing_access(team, user):
            args = ReadDataAdminAccessToolArgs
            billing_prompt = READ_DATA_BILLING_PROMPT
        description = cls._format_prompt(READ_DATA_PROMPT, billing_prompt=billing_prompt)
        return cls(team=team, user=user, state=state, config=config, args_schema=args, description=description)

    async def _arun_impl(self, kind: ReadDataAdminAccessKind | ReadDataKind) -> tuple[str, dict[str, Any] | None]:
        match kind:
            case "billing_info":
                has_access = await self._check_user_has_billing_access(self._team, self._user)
                if not has_access:
                    return BILLING_INSUFFICIENT_ACCESS_PROMPT, None
                # used for routing
                return "", ReadDataToolArgs(kind=kind).model_dump()
            case "datawarehouse_schema":
                return await self._serialize_database_schema(), None

    @classmethod
    @database_sync_to_async
    def _check_user_has_billing_access(self, team: Team, user: User) -> bool:
        """
        Check if the user has access to the billing tool.
        """
        return user.organization_memberships.get(organization=team.organization).level in (
            OrganizationMembership.Level.ADMIN,
            OrganizationMembership.Level.OWNER,
        )
