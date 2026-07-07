import uuid

import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.models import TaggedItem, Team, User

from products.customer_analytics.backend.max_tools import (
    AccountPropertiesInput,
    CreateAccountAction,
    UpdateAccountAction,
    UpsertAccountTool,
)
from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition


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

    @sync_to_async
    def _create_definition(self, name: str = "CSM") -> AccountRelationshipDefinition:
        return AccountRelationshipDefinition.objects.for_team(self.team.id).create(team_id=self.team.id, name=name)

    async def _active_holder_ids(self, account: Account) -> set[int]:
        return await sync_to_async(
            lambda: set(
                AccountRelationship.objects.for_team(self.team.id)
                .filter(account=account, ended_at__isnull=True)
                .values_list("user_id", flat=True)
            )
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
    async def test_create_with_properties_tags_and_relationships(self):
        await self._create_definition("CSM")

        _, artifact = await self._tool()._arun_impl(
            action=CreateAccountAction(
                name="Acme Corp",
                properties=AccountPropertiesInput(stripe_customer_id="cus_42"),
                tags=["enterprise", "priority"],
                relationships={"CSM": self.user.id},
            )
        )

        account = await sync_to_async(Account.objects.unscoped().get)(id=artifact["account_id"])
        assert account._properties["stripe_customer_id"] == "cus_42"
        assert await self._tags_for(account) == ["enterprise", "priority"]
        assert await self._active_holder_ids(account) == {self.user.id}

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_duplicate_external_id_returns_error(self):
        await self._tool()._arun_impl(action=CreateAccountAction(name="Acme", external_id="dup-1"))

        _, artifact = await self._tool()._arun_impl(action=CreateAccountAction(name="Acme 2", external_id="dup-1"))

        assert artifact["error"] == "duplicate_external_id"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_relationships_assigns_hands_off_and_ends(self):
        await self._create_definition("CSM")
        successor = await sync_to_async(self._create_user)("successor@posthog.com")
        account = await sync_to_async(Account.objects.unscoped().create)(team=self.team, name="Acme")

        _, artifact = await self._tool()._arun_impl(
            action=UpdateAccountAction(account_id=str(account.id), relationships={"CSM": self.user.id})
        )
        assert "error" not in artifact
        assert await self._active_holder_ids(account) == {self.user.id}

        await self._tool()._arun_impl(
            action=UpdateAccountAction(account_id=str(account.id), relationships={"CSM": successor.id})
        )
        assert await self._active_holder_ids(account) == {successor.id}

        await self._tool()._arun_impl(
            action=UpdateAccountAction(account_id=str(account.id), relationships={"CSM": None})
        )
        assert await self._active_holder_ids(account) == set()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_with_unknown_relationship_name_persists_nothing(self):
        await self._create_definition("CSM")

        content, artifact = await self._tool()._arun_impl(
            action=CreateAccountAction(name="Acme", relationships={"Account executive": self.user.id})
        )

        assert artifact["error"] == "invalid_relationship_assignment"
        assert "Account executive" in content
        assert "CSM" in content
        assert not await sync_to_async(Account.objects.unscoped().filter(team=self.team).exists)()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_relationship_with_non_member_user_returns_error(self):
        await self._create_definition("CSM")
        outsider = await sync_to_async(User.objects.create_user)("outsider@example.com", None, "")
        account = await sync_to_async(Account.objects.unscoped().create)(team=self.team, name="Acme")

        content, artifact = await self._tool()._arun_impl(
            action=UpdateAccountAction(account_id=str(account.id), relationships={"CSM": outsider.id})
        )

        assert artifact["error"] == "invalid_relationship_assignment"
        assert content == f"User {outsider.id} is not a member of this organization."
        assert await self._active_holder_ids(account) == set()

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_merges_properties_and_drops_legacy_role_keys(self):
        account = await sync_to_async(Account.objects.unscoped().create)(
            team=self.team,
            name="Acme Corp",
            _properties={"csm": {"id": 1, "email": "csm@acme.com"}, "stripe_customer_id": "cus_1"},
        )

        _, artifact = await self._tool()._arun_impl(
            action=UpdateAccountAction(
                account_id=str(account.id), properties=AccountPropertiesInput(billing_id="bill-1")
            )
        )

        assert "error" not in artifact
        refreshed = await sync_to_async(Account.objects.unscoped().get)(id=account.id)
        assert refreshed._properties["stripe_customer_id"] == "cus_1"
        assert refreshed._properties["billing_id"] == "bill-1"
        assert "csm" not in refreshed._properties

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
