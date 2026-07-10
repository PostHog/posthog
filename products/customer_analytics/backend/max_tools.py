from textwrap import dedent
from typing import TYPE_CHECKING, Any, Literal, Union

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from asgiref.sync import sync_to_async
from pydantic import BaseModel, ConfigDict, Field

from posthog.exceptions_capture import capture_exception
from posthog.models import OrganizationMembership
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject

from products.customer_analytics.backend.facade.api import _set_tags
from products.customer_analytics.backend.logic import relationships as relationships_logic
from products.customer_analytics.backend.models import Account, AccountRelationshipDefinition
from products.notebooks.backend.models import Notebook, ResourceNotebook

from ee.hogai.tool import MaxTool
from ee.hogai.tools.create_notebook.tiptap import markdown_to_tiptap_nodes

if TYPE_CHECKING:
    from posthog.models import Team


async def _aget_account_by_id(team: "Team", account_id: str) -> Account | None:
    """Resolve an account by id within a team. Account is fail-closed, so the
    unscoped manager is used with an explicit team filter."""
    account_id = str(account_id).strip()
    if not account_id:
        return None
    try:
        return await Account.objects.unscoped().aget(id=account_id, team=team)
    except (Account.DoesNotExist, ValidationError, ValueError):
        return None


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
    `properties` carries typed fields. External-system ids (stripe_customer_id, hubspot_deal_id,
    billing_id, sfdc_id, zendesk_id) are strings.
    On **update**, only the property keys you pass are changed (others are preserved); pass a key as
    null to clear it.

    # Relationships
    Pass `relationships` to assign users to the account's relationships (CSM, Account executive, or
    any definition the team has created), keyed by definition name: the value is the PostHog user id,
    or null to end the current assignment. Only the named definitions are changed.

    # Tags
    Pass `tags` to set the account's tags. On update this REPLACES the existing tag set.

    # Examples
    - "Add an account for Acme Corp whose PostHog group key is acme-123": action=create, name="Acme Corp", external_id="acme-123"
    - "Assign Jane (user 42) as CSM for that account": action=update, account_id=<uuid>,
      relationships={CSM: 42}
    - "Tag it enterprise and priority": action=update, account_id=<uuid>, tags=["enterprise", "priority"]
    """).strip()


class RelationshipAssignmentError(Exception):
    pass


class AccountPropertiesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    relationships: dict[str, int | None] | None = Field(
        default=None,
        description=(
            "Relationship assignments keyed by definition name (e.g. 'CSM'); each value is the "
            "PostHog user id to assign, or null to end the current assignment."
        ),
    )


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
    relationships: dict[str, int | None] | None = Field(
        default=None,
        description=(
            "Relationship assignments keyed by definition name (e.g. 'CSM'); each value is the "
            "PostHog user id to assign, or null to end the current assignment. Only the named "
            "definitions are changed."
        ),
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
        except RelationshipAssignmentError as e:
            return str(e), {"error": "invalid_relationship_assignment"}
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create account: {str(e)}", {"error": "creation_failed", "details": str(e)}

        return (
            f"Account '{account.name}' created successfully.",
            self._artifact(account),
        )

    async def _handle_update(self, action: UpdateAccountAction) -> tuple[str, dict[str, Any]]:
        account = await _aget_account_by_id(self._team, action.account_id)
        if account is None:
            return f"Account '{action.account_id}' not found.", {"error": "account_not_found"}

        await self.check_object_access(account, "editor", resource="account", action="edit")

        if (
            action.name is None
            and action.external_id is None
            and action.tags is None
            and action.properties is None
            and action.relationships is None
        ):
            return "No changes provided. Specify at least one field to update.", {"error": "no_changes"}

        try:
            account = await self._update_account(account, action)
        except IntegrityError:
            return f"An account with external_id '{action.external_id}' already exists for this team.", {
                "error": "duplicate_external_id",
            }
        except RelationshipAssignmentError as e:
            return str(e), {"error": "invalid_relationship_assignment"}
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

    @sync_to_async
    def _create_account(self, action: CreateAccountAction, properties: dict[str, Any]) -> Account:
        with transaction.atomic():
            account = Account.objects.create_account(
                team=self._team,
                created_by=self._user,
                name=action.name,
                external_id=(action.external_id or None),
                properties=properties,
            )
            if action.tags is not None:
                _set_tags(action.tags, account, actor=self._user)
            if action.relationships:
                self._apply_relationship_assignments(account, action.relationships)
        return account

    @sync_to_async
    def _update_account(self, account: Account, action: UpdateAccountAction) -> Account:
        update_kwargs: dict[str, Any] = {}
        if action.name is not None:
            update_kwargs["name"] = action.name
        if action.external_id is not None:
            update_kwargs["external_id"] = action.external_id or None
        if action.properties is not None:
            properties = account.properties.model_dump(mode="json")
            properties.update(action.properties.model_dump(exclude_unset=True))
            update_kwargs["properties"] = properties
        with transaction.atomic():
            account = Account.objects.update_account(account, **update_kwargs)
            if action.tags is not None:
                _set_tags(action.tags, account, actor=self._user)
            if action.relationships:
                self._apply_relationship_assignments(account, action.relationships)
        return account

    def _apply_relationship_assignments(self, account: Account, assignments: dict[str, int | None]) -> None:
        definitions = {
            definition.name: definition
            for definition in AccountRelationshipDefinition.objects.for_team(self._team.id).filter(
                name__in=assignments.keys()
            )
        }
        unknown = next((name for name in assignments if name not in definitions), None)
        if unknown is not None:
            available = AccountRelationshipDefinition.objects.for_team(self._team.id).values_list("name", flat=True)
            raise RelationshipAssignmentError(
                f"Unknown relationship definition '{unknown}'. Available: {', '.join(sorted(available)) or 'none'}."
            )
        user_ids = {user_id for user_id in assignments.values() if user_id is not None}
        memberships = {
            membership.user_id: membership
            for membership in OrganizationMembership.objects.select_related("user").filter(
                organization_id=self._team.organization_id, user_id__in=user_ids
            )
        }
        missing = sorted(user_ids - memberships.keys())
        if missing:
            raise RelationshipAssignmentError(f"User {missing[0]} is not a member of this organization.")
        for name, user_id in assignments.items():
            definition = definitions[name]
            if user_id is None:
                relationships_logic.end_active(team_id=self._team.id, account=account, definition=definition)
                continue
            relationships_logic.assign(
                team_id=self._team.id,
                account=account,
                definition=definition,
                user=memberships[user_id].user,
                created_by=self._user,
            )


UPSERT_ACCOUNT_NOTEBOOK_TOOL_DESCRIPTION = dedent("""
    Create or update a note attached to a customer account — a call recap, a meeting summary, an
    investigation timeline, or any free-form context worth persisting. Notes appear under the
    account's Notes tab in the Accounts list. Write the note body (`content`) in Markdown.

    # Actions
    - **create**: Add a new note to an account (requires `account_id`, a UUID). If you only have a
      name, resolve the account first with read_data/list_data using the account kind.
    - **update**: Revise an existing note (requires `notebook_short_id`). Pass a new `title` and/or
      `content`; `content` REPLACES the existing body, so send the full updated note, not just the
      change. Use the short_id returned when the note was created.
    """).strip()


def _tiptap_doc(markdown: str) -> dict[str, Any]:
    return {"type": "doc", "content": markdown_to_tiptap_nodes(markdown) or [{"type": "paragraph"}]}


class CreateAccountNotebookAction(BaseModel):
    action: Literal["create"] = "create"
    account_id: str = Field(description="UUID of the account to attach the note to.")
    title: str = Field(description="Short, descriptive title, e.g. 'Q3 kickoff call recap'.")
    content: str = Field(description="The note body in Markdown.")


class UpdateAccountNotebookAction(BaseModel):
    action: Literal["update"] = "update"
    notebook_short_id: str = Field(description="short_id of the account note to update.")
    title: str | None = Field(default=None, description="New title; leave unset to keep the current one.")
    content: str | None = Field(
        default=None,
        description="New note body in Markdown; replaces the existing content. Leave unset to keep it.",
    )


UpsertAccountNotebookAction = Union[CreateAccountNotebookAction, UpdateAccountNotebookAction]


class UpsertAccountNotebookToolArgs(BaseModel):
    action: UpsertAccountNotebookAction = Field(
        description="Create a new account note or update an existing one.",
        discriminator="action",
    )


class UpsertAccountNotebookTool(MaxTool):
    name: str = "upsert_account_notebook"
    description: str = UPSERT_ACCOUNT_NOTEBOOK_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = UpsertAccountNotebookToolArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("account", "editor")]

    async def _arun_impl(self, action: UpsertAccountNotebookAction) -> tuple[str, dict[str, Any]]:
        if isinstance(action, CreateAccountNotebookAction):
            return await self._handle_create(action)
        return await self._handle_update(action)

    async def _handle_create(self, action: CreateAccountNotebookAction) -> tuple[str, dict[str, Any]]:
        account = await _aget_account_by_id(self._team, action.account_id)
        if account is None:
            return f"Account '{action.account_id}' not found.", {"error": "account_not_found"}

        await self.check_object_access(account, "editor", resource="account", action="edit")

        try:
            notebook = await self._create_notebook(account, action)
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create the note: {str(e)}", {"error": "creation_failed", "details": str(e)}

        return f"Created the note '{notebook.title}' on {account.name}.", self._artifact(notebook, account)

    async def _handle_update(self, action: UpdateAccountNotebookAction) -> tuple[str, dict[str, Any]]:
        if action.title is None and action.content is None:
            return "No changes provided. Specify a new title or content.", {"error": "no_changes"}

        resolved = await self._resolve_account_notebook(action.notebook_short_id)
        if resolved is None:
            return f"Account note '{action.notebook_short_id}' not found.", {"error": "notebook_not_found"}
        notebook, account = resolved

        await self.check_object_access(account, "editor", resource="account", action="edit")

        try:
            notebook = await self._update_notebook(notebook, action)
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to update the note: {str(e)}", {"error": "update_failed", "details": str(e)}

        return f"Updated the note '{notebook.title}' on {account.name}.", self._artifact(notebook, account)

    @staticmethod
    def _artifact(notebook: Notebook, account: Account) -> dict[str, Any]:
        return {
            "account_id": str(account.id),
            "account_name": account.name,
            "external_id": account.external_id,
            "notebook_short_id": notebook.short_id,
            "title": notebook.title,
        }

    async def _resolve_account_notebook(self, short_id: str) -> tuple[Notebook, Account] | None:
        short_id = str(short_id).strip()
        if not short_id:
            return None
        try:
            link = (
                await ResourceNotebook.objects.filter(
                    notebook__short_id=short_id,
                    notebook__team=self._team,
                    notebook__deleted=False,
                    notebook__visibility=Notebook.Visibility.INTERNAL,
                    account__isnull=False,
                )
                .select_related("notebook", "account")
                .afirst()
            )
        except (ValidationError, ValueError):
            return None
        if link is None or link.account is None:
            return None
        return link.notebook, link.account

    @sync_to_async
    def _create_notebook(self, account: Account, action: CreateAccountNotebookAction) -> Notebook:
        with transaction.atomic():
            notebook = Notebook.objects.create(
                team=self._team,
                created_by=self._user,
                last_modified_by=self._user,
                visibility=Notebook.Visibility.INTERNAL,
                title=action.title[:256],
                text_content=action.content,
                content=_tiptap_doc(action.content),
            )
            ResourceNotebook.objects.create(notebook=notebook, account=account)
        return notebook

    @sync_to_async
    def _update_notebook(self, notebook: Notebook, action: UpdateAccountNotebookAction) -> Notebook:
        with transaction.atomic():
            locked = Notebook.objects.select_for_update().get(pk=notebook.pk)
            locked.last_modified_at = timezone.now()
            locked.last_modified_by = self._user
            update_fields = ["last_modified_at", "last_modified_by"]
            if action.title is not None:
                locked.title = action.title[:256]
                update_fields.append("title")
            if action.content is not None:
                locked.content = _tiptap_doc(action.content)
                locked.text_content = action.content
                locked.version = locked.version + 1
                update_fields += ["content", "text_content", "version"]
            locked.save(update_fields=update_fields)
        return locked
