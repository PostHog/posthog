from textwrap import dedent
from typing import Any, Literal

from django.core.exceptions import ValidationError

from pydantic import BaseModel, Field

from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject

from products.customer_analytics.backend.models import Account

from ee.hogai.tool import MaxTool

OPEN_ACCOUNT_TOOL_DESCRIPTION = dedent("""
    Open an account in the Accounts list and jump to one of its tabs — Notes, Users, or Usage.

    Use this to show the user an account's existing usage (the Usage tab) instead of building a new
    insight, or to surface its notes or related users. Identify the account by name or external id;
    `tab` defaults to usage. The account must be in the list the user is currently viewing.
    """).strip()


class OpenAccountToolArgs(BaseModel):
    account: str = Field(description="The account to open — its name or external id.")
    tab: Literal["notes", "users", "usage"] = Field(
        default="usage",
        description="Which tab to open: notes, users, or usage. Defaults to usage.",
    )


class OpenAccountTool(MaxTool):
    name: str = "open_account"
    description: str = OPEN_ACCOUNT_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = OpenAccountToolArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("account", "viewer")]

    async def _arun_impl(self, account: str, tab: str = "usage") -> tuple[str, dict[str, Any]]:
        resolved = await self._resolve_account(account)
        if resolved is None:
            return f"Couldn't find an account matching '{account}'.", {"error": "account_not_found"}
        await self.check_object_access(resolved, "viewer", resource="account", action="read")
        return (
            f"Opened {resolved.name}'s {tab} tab.",
            {
                "account_id": str(resolved.id),
                "account_name": resolved.name,
                "external_id": resolved.external_id,
                "tab": tab,
            },
        )

    async def _resolve_account(self, account: str) -> Account | None:
        account = account.strip()
        if not account:
            return None
        accounts = Account.objects.unscoped().filter(team=self._team)
        try:
            match = await accounts.filter(external_id=account).afirst()
            if match is None:
                match = await accounts.filter(name__iexact=account).afirst()
            return match
        except (ValidationError, ValueError):
            return None
