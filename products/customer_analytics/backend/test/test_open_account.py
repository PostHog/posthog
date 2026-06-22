import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.models import Team

from products.customer_analytics.backend.max_tools import OpenAccountTool
from products.customer_analytics.backend.models import Account


class TestOpenAccountTool(BaseTest):
    def setUp(self):
        super().setUp()
        self._config: RunnableConfig = {"configurable": {"team": self.team, "user": self.user}}

    def _tool(self) -> OpenAccountTool:
        return OpenAccountTool(team=self.team, user=self.user, config=self._config)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_resolves_by_external_id_defaulting_to_usage_tab(self):
        account = await sync_to_async(Account.objects.unscoped().create)(
            team=self.team, name="Acme Corp", external_id="acme-123"
        )

        content, artifact = await self._tool()._arun_impl(account="acme-123")

        assert "Acme Corp" in content
        assert artifact["account_id"] == str(account.id)
        assert artifact["external_id"] == "acme-123"
        assert artifact["tab"] == "usage"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_resolves_by_name_case_insensitive_and_keeps_tab(self):
        account = await sync_to_async(Account.objects.unscoped().create)(team=self.team, name="Acme Corp")

        _, artifact = await self._tool()._arun_impl(account="acme corp", tab="notes")

        assert artifact["account_id"] == str(account.id)
        assert artifact["tab"] == "notes"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_unknown_account_returns_error(self):
        content, artifact = await self._tool()._arun_impl(account="nonexistent")

        assert "Couldn't find" in content
        assert artifact["error"] == "account_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_account_from_other_team_is_not_found(self):
        other_team = await sync_to_async(lambda: Team.objects.create(organization=self.organization))()
        await sync_to_async(Account.objects.unscoped().create)(team=other_team, name="Foreign", external_id="foreign-1")

        _, artifact = await self._tool()._arun_impl(account="foreign-1")

        assert artifact["error"] == "account_not_found"
