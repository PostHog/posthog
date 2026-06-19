from textwrap import dedent
from typing import Any, Literal, Union

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from asgiref.sync import sync_to_async
from pydantic import BaseModel, Field

from posthog.exceptions_capture import capture_exception
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject

from products.customer_analytics.backend.models import Account
from products.notebooks.backend.models import Notebook, ResourceNotebook

from ee.hogai.tool import MaxTool
from ee.hogai.tools.create_notebook.tiptap import markdown_to_tiptap_nodes

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
        account = await self._resolve_account(action.account_id)
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

    async def _resolve_account(self, account_id: str) -> Account | None:
        account_id = str(account_id).strip()
        if not account_id:
            return None
        try:
            return await Account.objects.unscoped().aget(id=account_id, team=self._team)
        except (Account.DoesNotExist, ValidationError, ValueError):
            return None

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
