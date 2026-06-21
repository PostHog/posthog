import uuid

import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.models import TaggedItem, Team

from products.customer_analytics.backend.max_tools import (
    AccountAssignment,
    AccountPropertiesInput,
    CreateAccountAction,
    UpdateAccountAction,
    UpsertAccountTool,
)
from products.customer_analytics.backend.models import Account


class TestUpsertAccountTool(BaseTest):
    def setUp(self):
        super().setUp()
        self._config: RunnableConfig = {"configurable": {"team": self.team, "user": self.user}}

    def _tool(self) -> UpsertAccountTool:
        return UpsertAccountTool(team=self.team, user=self.user, config=self._config)

    async def _tags_for(self, account: Account) -> list[str]:
        return await sync_to_async(
            lambda: sorted(TaggedItem.objects.filter(account=account).values_list("tag__name", flat=True))
        )()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_account(self):
        content, artifact = await self._tool()._arun_impl(
            action=CreateAccountAction(name="Acme Corp", external_id="acme-1")
        )

        assert "created successfully" in content
        account = await sync_to_async(Account.objects.unscoped().get)(id=artifact["account_id"])
        assert account.name == "Acme Corp"
        assert account.external_id == "acme-1"
        assert account.team_id == self.team.id
        assert account.created_by_id == self.user.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_with_properties_and_tags(self):
        _, artifact = await self._tool()._arun_impl(
            action=CreateAccountAction(
                name="Acme Corp",
                properties=AccountPropertiesInput(csm=AccountAssignment(id=self.user.id, email=self.user.email)),
                tags=["enterprise", "priority"],
            )
        )

        account = await sync_to_async(Account.objects.unscoped().get)(id=artifact["account_id"])
        assert account._properties["csm"] == {"id": self.user.id, "email": self.user.email}
        assert await self._tags_for(account) == ["enterprise", "priority"]

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_duplicate_external_id_returns_error(self):
        await self._tool()._arun_impl(action=CreateAccountAction(name="Acme", external_id="dup-1"))

        _, artifact = await self._tool()._arun_impl(action=CreateAccountAction(name="Acme 2", external_id="dup-1"))

        assert artifact["error"] == "duplicate_external_id"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_assigns_role_and_merges_properties(self):
        account = await sync_to_async(Account.objects.unscoped().create)(
            team=self.team, name="Acme Corp", _properties={"csm": {"id": 1, "email": "csm@acme.com"}}
        )

        _, artifact = await self._tool()._arun_impl(
            action=UpdateAccountAction(
                account_id=str(account.id),
                properties=AccountPropertiesInput(
                    account_owner=AccountAssignment(id=self.user.id, email=self.user.email)
                ),
            )
        )

        refreshed = await sync_to_async(Account.objects.unscoped().get)(id=account.id)
        assert refreshed._properties["csm"] == {"id": 1, "email": "csm@acme.com"}
        assert refreshed._properties["account_owner"] == {"id": self.user.id, "email": self.user.email}

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_replaces_tags(self):
        _, created = await self._tool()._arun_impl(action=CreateAccountAction(name="Acme", tags=["old"]))
        account = await sync_to_async(Account.objects.unscoped().get)(id=created["account_id"])

        await self._tool()._arun_impl(action=UpdateAccountAction(account_id=str(account.id), tags=["new"]))

        assert await self._tags_for(account) == ["new"]

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_unknown_account_returns_error(self):
        _, artifact = await self._tool()._arun_impl(action=UpdateAccountAction(account_id=str(uuid.uuid4()), name="x"))

        assert artifact["error"] == "account_not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_with_no_fields_returns_error(self):
        account = await sync_to_async(Account.objects.unscoped().create)(team=self.team, name="Acme")

        _, artifact = await self._tool()._arun_impl(action=UpdateAccountAction(account_id=str(account.id)))

        assert artifact["error"] == "no_changes"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_account_from_other_team_is_not_found(self):
        other_team = await sync_to_async(lambda: Team.objects.create(organization=self.organization))()
        account = await sync_to_async(Account.objects.unscoped().create)(team=other_team, name="Foreign")

        _, artifact = await self._tool()._arun_impl(action=UpdateAccountAction(account_id=str(account.id), name="x"))

        assert artifact["error"] == "account_not_found"
