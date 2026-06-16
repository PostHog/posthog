from textwrap import dedent
from typing import Any, Literal, Union

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from asgiref.sync import sync_to_async
from pydantic import BaseModel, ConfigDict, Field

from posthog.api.tagged_item import set_tags_on_object
from posthog.exceptions_capture import capture_exception
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject

from products.customer_analytics.backend.models import Account

from ee.hogai.tool import MaxTool

UPSERT_ACCOUNT_TOOL_DESCRIPTION = dedent("""
    Use this tool to create a new customer account or update an existing one.

    An account represents a customer organization. Its `external_id` must be the id PostHog uses to
    identify that organization in group analytics (its group key) — this is what links the account to
    its usage and activity data, so it must match exactly. Do NOT put a CRM or billing id here; record
    those with the dedicated properties (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id,
    zendesk_id).

    # Actions
    - **create**: Create a new account (requires `name`).
    - **update**: Edit an existing account (requires `account_id`; all other fields optional).

    # Finding an account to update
    Resolve `account_id` (a UUID) first via `read_data`/`list_data` with the account kind.

    # Properties
    `properties` carries typed fields. Assignment fields (csm, account_executive, account_owner) take
    an object `{id, email}` (the PostHog user id and email) or null to clear. External-system ids
    (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id) are strings.
    On **update**, only the property keys you pass are changed (others are preserved); pass a key as
    null to clear it.

    # Tags
    Pass `tags` to set the account's tags. On update this REPLACES the existing tag set.

    # Examples
    - "Add an account for Acme Corp whose PostHog group key is acme-123": action=create, name="Acme Corp", external_id="acme-123"
    - "Assign Jane (user 42, jane@acme.com) as CSM for that account": action=update, account_id=<uuid>,
      properties={csm: {id: 42, email: "jane@acme.com"}}
    - "Tag it enterprise and priority": action=update, account_id=<uuid>, tags=["enterprise", "priority"]
    """).strip()


class AccountAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(description="PostHog user id of the assignee")
    email: str = Field(description="Email of the assignee")


class AccountPropertiesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csm: AccountAssignment | None = Field(default=None, description="Customer success manager assignment")
    account_executive: AccountAssignment | None = Field(default=None, description="Account executive assignment")
    account_owner: AccountAssignment | None = Field(default=None, description="Account owner assignment")
    stripe_customer_id: str | None = Field(default=None, description="Stripe customer id")
    hubspot_deal_id: str | None = Field(default=None, description="HubSpot deal id")
    billing_id: str | None = Field(default=None, description="Billing system id")
    sfdc_id: str | None = Field(default=None, description="Salesforce id")
    zendesk_id: str | None = Field(default=None, description="Zendesk id")


class CreateAccountAction(BaseModel):
    action: Literal["create"] = "create"
    name: str = Field(description="Human-readable account name, e.g. 'Acme Corp'")
    external_id: str | None = Field(
        default=None,
        description=(
            "The id PostHog uses to identify this organization in group analytics (its group key). "
            "Links the account to its usage and activity data, so it must match exactly. Do not put a "
            "CRM/billing id here — record those with the properties fields. Optional but strongly "
            "recommended."
        ),
    )
    tags: list[str] | None = Field(default=None, description="Tag names to attach to the account")
    properties: AccountPropertiesInput | None = Field(default=None, description="Typed account properties")


class UpdateAccountAction(BaseModel):
    action: Literal["update"] = "update"
    account_id: str = Field(description="UUID of the account to update")
    name: str | None = Field(default=None, description="New account name")
    external_id: str | None = Field(
        default=None,
        description="New external id — the organization's group key in PostHog, not a CRM/billing id.",
    )
    tags: list[str] | None = Field(default=None, description="Replaces the account's existing tags")
    properties: AccountPropertiesInput | None = Field(
        default=None, description="Property keys to merge; pass a key as null to clear it"
    )


UpsertAccountAction = Union[CreateAccountAction, UpdateAccountAction]


class UpsertAccountToolArgs(BaseModel):
    action: UpsertAccountAction = Field(
        description="Create a new account or update an existing one.",
        discriminator="action",
    )


class UpsertAccountTool(MaxTool):
    name: str = "upsert_account"
    description: str = UPSERT_ACCOUNT_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = UpsertAccountToolArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("account", "editor")]

    async def _arun_impl(self, action: UpsertAccountAction) -> tuple[str, dict[str, Any]]:
        if isinstance(action, CreateAccountAction):
            return await self._handle_create(action)
        return await self._handle_update(action)

    async def _handle_create(self, action: CreateAccountAction) -> tuple[str, dict[str, Any]]:
        properties = action.properties.model_dump(exclude_unset=True) if action.properties is not None else {}
        try:
            account = await self._create_account(action, properties)
        except IntegrityError:
            return f"An account with external_id '{action.external_id}' already exists for this team.", {
                "error": "duplicate_external_id",
            }
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create account: {str(e)}", {"error": "creation_failed", "details": str(e)}

        return (
            f"Account '{account.name}' created successfully.",
            self._artifact(account),
        )

    async def _handle_update(self, action: UpdateAccountAction) -> tuple[str, dict[str, Any]]:
        account = await self._resolve_account(action.account_id)
        if account is None:
            return f"Account '{action.account_id}' not found.", {"error": "account_not_found"}

        await self.check_object_access(account, "editor", resource="account", action="edit")

        if action.name is None and action.external_id is None and action.tags is None and action.properties is None:
            return "No changes provided. Specify at least one field to update.", {"error": "no_changes"}

        try:
            account = await self._update_account(account, action)
        except IntegrityError:
            return f"An account with external_id '{action.external_id}' already exists for this team.", {
                "error": "duplicate_external_id",
            }
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to update account: {str(e)}", {"error": "update_failed", "details": str(e)}

        return (
            f"Account '{account.name}' updated successfully.",
            self._artifact(account),
        )

    @staticmethod
    def _artifact(account: Account) -> dict[str, Any]:
        return {
            "account_id": str(account.id),
            "name": account.name,
            "external_id": account.external_id,
        }

    async def _resolve_account(self, account_id: str) -> Account | None:
        account_id = str(account_id).strip()
        if not account_id:
            return None
        try:
            return await Account.objects.unscoped().aget(id=account_id, team=self._team)
        except (Account.DoesNotExist, ValidationError, ValueError):
            return None

    @sync_to_async
    def _create_account(self, action: CreateAccountAction, properties: dict[str, Any]) -> Account:
        with transaction.atomic():
            account = Account.objects.unscoped().create(
                team=self._team,
                created_by=self._user,
                name=action.name[:400],
                external_id=(action.external_id[:400] if action.external_id else None),
                _properties=properties,
            )
            if action.tags is not None:
                set_tags_on_object(action.tags, account)
        return account

    @sync_to_async
    def _update_account(self, account: Account, action: UpdateAccountAction) -> Account:
        with transaction.atomic():
            update_fields: list[str] = []
            if action.name is not None:
                account.name = action.name[:400]
                update_fields.append("name")
            if action.external_id is not None:
                account.external_id = action.external_id[:400] or None
                update_fields.append("external_id")
            if action.properties is not None:
                merged = {**(account._properties or {}), **action.properties.model_dump(exclude_unset=True)}
                account._properties = merged
                update_fields.append("_properties")
            if update_fields:
                account.save(update_fields=update_fields)
            if action.tags is not None:
                set_tags_on_object(action.tags, account)
        return account
