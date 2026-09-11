import uuid

import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.models import Team

from products.customer_analytics.backend.max_tools import (
    CreateAccountNotebookAction,
    UpdateAccountNotebookAction,
    UpsertAccountNotebookTool,
)
from products.customer_analytics.backend.models import Account
from products.notebooks.backend.facade.content import build_markdown_notebook_content, is_markdown_notebook_content
from products.notebooks.backend.models import Notebook, ResourceNotebook


class TestUpsertAccountNotebookTool(BaseTest):
    def setUp(self):
        super().setUp()
        self._config: RunnableConfig = {"configurable": {"team": self.team, "user": self.user}}

    def _tool(self) -> UpsertAccountNotebookTool:
        return UpsertAccountNotebookTool(team=self.team, user=self.user, config=self._config)

    async def _create_note(
        self, account: Account, title: str = "Q3 recap", content: str = "# Summary\n\nSSO by Q3."
    ) -> str:
        _, artifact = await self._tool()._arun_impl(
            action=CreateAccountNotebookAction(account_id=str(account.id), title=title, content=content)
        )
        return artifact["notebook_short_id"]

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_links_internal_notebook_to_account(self):
        account = await sync_to_async(Account.objects.unscoped().create)(team=self.team, name="Acme Corp")

        content, artifact = await self._tool()._arun_impl(
            action=CreateAccountNotebookAction(
                account_id=str(account.id), title="Q3 call recap", content="# Summary\n\nThey want SSO by Q3."
            )
        )

        assert "Acme Corp" in content
        assert artifact["account_id"] == str(account.id)

        notebook = await sync_to_async(Notebook.objects.get)(short_id=artifact["notebook_short_id"])
        assert notebook.team_id == self.team.id
        assert notebook.visibility == Notebook.Visibility.INTERNAL
        assert notebook.created_by_id == self.user.id
        assert notebook.title == "Q3 call recap"
        assert notebook.content == build_markdown_notebook_content("# Summary\n\nThey want SSO by Q3.")
        assert notebook.text_content == "# Summary\n\nThey want SSO by Q3."
        assert notebook.version == 0

        linked = await sync_to_async(ResourceNotebook.objects.filter(notebook=notebook, account=account).exists)()
        assert linked

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_blank_markdown_stores_an_empty_markdown_notebook(self):
        account = await sync_to_async(Account.objects.unscoped().create)(team=self.team, name="Beta Inc")

        _, artifact = await self._tool()._arun_impl(
            action=CreateAccountNotebookAction(account_id=str(account.id), title="Empty", content="")
        )

        notebook = await sync_to_async(Notebook.objects.get)(short_id=artifact["notebook_short_id"])
        assert notebook.content == build_markdown_notebook_content("")

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_account_not_found_returns_error(self):
        content, artifact = await self._tool()._arun_impl(
            action=CreateAccountNotebookAction(account_id=str(uuid.uuid4()), title="x", content="y")
        )

        assert "not found" in content
        assert artifact["error"] == "account_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_account_from_other_team_is_not_found(self):
        other_team = await sync_to_async(lambda: Team.objects.create(organization=self.organization))()
        account = await sync_to_async(Account.objects.unscoped().create)(team=other_team, name="Foreign")

        _, artifact = await self._tool()._arun_impl(
            action=CreateAccountNotebookAction(account_id=str(account.id), title="x", content="y")
        )

        assert artifact["error"] == "account_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_changes_title_and_content_and_bumps_version(self):
        account = await sync_to_async(Account.objects.unscoped().create)(team=self.team, name="Acme Corp")
        short_id = await self._create_note(account)

        content, artifact = await self._tool()._arun_impl(
            action=UpdateAccountNotebookAction(
                notebook_short_id=short_id,
                title="Q3 recap (updated)",
                content="# Summary\n\nSSO by Q3.\n\n## Pricing\n\nAsked about SSO pricing.",
            )
        )

        assert "Acme Corp" in content
        assert artifact["notebook_short_id"] == short_id

        notebook = await sync_to_async(Notebook.objects.get)(short_id=short_id)
        assert notebook.title == "Q3 recap (updated)"
        assert notebook.content == build_markdown_notebook_content(
            "# Summary\n\nSSO by Q3.\n\n## Pricing\n\nAsked about SSO pricing."
        )
        assert notebook.text_content is not None and "Pricing" in notebook.text_content
        assert notebook.version == 1

    @parameterized.expand(
        [
            ("holding a node", [{"type": "paragraph"}]),
            ("empty", []),
        ]
    )
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_keeps_a_rich_text_note_in_rich_text(self, _name: str, stored_nodes: list) -> None:
        def _make_rich_text_note() -> str:
            account = Account.objects.unscoped().create(team=self.team, name="Legacy Corp")
            notebook = Notebook.objects.create(
                team=self.team,
                title="Legacy note",
                content={"type": "doc", "content": stored_nodes},
                visibility=Notebook.Visibility.INTERNAL,
            )
            ResourceNotebook.objects.create(notebook=notebook, account=account)
            return notebook.short_id

        short_id = await sync_to_async(_make_rich_text_note)()

        _, artifact = await self._tool()._arun_impl(
            action=UpdateAccountNotebookAction(notebook_short_id=short_id, content="# Later\n\nStill rich text.")
        )

        assert artifact["notebook_short_id"] == short_id
        notebook = await sync_to_async(Notebook.objects.get)(short_id=short_id)
        assert not is_markdown_notebook_content(notebook.content)
        assert notebook.content["content"][0]["type"] == "heading"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_with_no_fields_returns_error(self):
        _, artifact = await self._tool()._arun_impl(action=UpdateAccountNotebookAction(notebook_short_id="abc123"))

        assert artifact["error"] == "no_changes"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_unknown_notebook_returns_error(self):
        _, artifact = await self._tool()._arun_impl(
            action=UpdateAccountNotebookAction(notebook_short_id="zzzzzzzzzzzz", content="x")
        )

        assert artifact["error"] == "notebook_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_notebook_from_other_team_is_not_found(self):
        def _make_foreign_note() -> str:
            other_team = Team.objects.create(organization=self.organization)
            other_account = Account.objects.unscoped().create(team=other_team, name="Foreign")
            notebook = Notebook.objects.create(
                team=other_team, title="Foreign", content={}, visibility=Notebook.Visibility.INTERNAL
            )
            ResourceNotebook.objects.create(notebook=notebook, account=other_account)
            return notebook.short_id

        foreign_short_id = await sync_to_async(_make_foreign_note)()

        _, artifact = await self._tool()._arun_impl(
            action=UpdateAccountNotebookAction(notebook_short_id=foreign_short_id, content="x")
        )

        assert artifact["error"] == "notebook_not_found"
