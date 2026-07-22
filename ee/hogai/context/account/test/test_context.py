import uuid
from typing import TYPE_CHECKING

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import MagicMock, PropertyMock, patch

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist

from asgiref.sync import sync_to_async

from posthog.api.tagged_item import set_tags_on_object

from products.notebooks.backend.models import Notebook, ResourceNotebook

if TYPE_CHECKING:
    from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition
else:
    Account = apps.get_model("customer_analytics", "Account")
    AccountRelationship = apps.get_model("customer_analytics", "AccountRelationship")
    AccountRelationshipDefinition = apps.get_model("customer_analytics", "AccountRelationshipDefinition")

from ee.hogai.context.account.context import AccountContext


class TestAccountContext(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    async def _create_account(self, **kwargs) -> Account:
        return await sync_to_async(Account.objects.unscoped().create)(team=self.team, **kwargs)

    async def test_aget_account_by_id(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        fetched = await AccountContext(team=self.team, user=self.user, account_id=str(account.id)).aget_account()

        assert fetched is not None
        assert fetched.id == account.id

    async def test_aget_account_by_external_id(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        fetched = await AccountContext(team=self.team, user=self.user, external_id="acme-1").aget_account()

        assert fetched is not None
        assert fetched.id == account.id

    async def test_aget_account_invalid_id_returns_none(self):
        assert await AccountContext(team=self.team, user=self.user, account_id="not-a-uuid").aget_account() is None

    async def test_aget_account_denied_by_access_control_is_not_found(self):
        # An account the caller can't read object-level must be indistinguishable from a missing one.
        account = await self._create_account(name="Acme Corp", external_id="acme-1")
        context = AccountContext(team=self.team, user=self.user, account_id=str(account.id))

        with patch.object(AccountContext, "user_access_control", new_callable=PropertyMock) as mock_uac:
            mock_uac.return_value.check_access_level_for_resource.return_value = True
            mock_uac.return_value.filter_queryset_by_access_level.side_effect = lambda qs: qs.none()

            assert await context.aget_account() is None
            result = await context.execute_and_format()

        assert "was not found" in result

    async def test_execute_and_format_not_found(self):
        result = await AccountContext(team=self.team, user=self.user, account_id=str(uuid.uuid4())).execute_and_format()

        assert "was not found" in result

    async def test_format_includes_basics(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        result = await AccountContext(team=self.team, user=self.user, account_id=str(account.id)).execute_and_format()

        assert "## Account: Acme Corp" in result
        assert str(account.id) in result
        assert "acme-1" in result

    async def test_format_external_id_not_set(self):
        account = await self._create_account(name="Acme Corp")

        result = await AccountContext(team=self.team, user=self.user, account_id=str(account.id)).execute_and_format()

        assert "**External ID:** Not set" in result

    async def test_format_includes_relationships(self):
        account = await self._create_account(name="Acme Corp")
        definition = await AccountRelationshipDefinition.objects.unscoped().acreate(team=self.team, name="CSM")
        await AccountRelationship.objects.unscoped().acreate(
            team=self.team, account=account, definition=definition, user=self.user
        )

        result = await AccountContext(team=self.team, user=self.user, account_id=str(account.id)).execute_and_format()

        assert "### Relationships" in result
        assert f"CSM: {self.user.email} (user {self.user.id})" in result

    async def test_format_omits_relationships_section_without_assignments(self):
        account = await self._create_account(name="Acme Corp")

        result = await AccountContext(team=self.team, user=self.user, account_id=str(account.id)).execute_and_format()

        assert "### Relationships" not in result

    async def test_format_includes_external_system_ids(self):
        account = await self._create_account(name="Acme Corp", _properties={"stripe_customer_id": "cus_123"})

        result = await AccountContext(team=self.team, user=self.user, account_id=str(account.id)).execute_and_format()

        assert "### External-system ids" in result
        assert "Stripe customer id: cus_123" in result

    async def test_format_includes_tags(self):
        account = await self._create_account(name="Acme Corp")
        await sync_to_async(set_tags_on_object)(["enterprise", "priority"], account)

        result = await AccountContext(team=self.team, user=self.user, account_id=str(account.id)).execute_and_format()

        assert "### Tags" in result
        assert "enterprise, priority" in result

    async def test_format_includes_saved_notes(self):
        account = await self._create_account(name="Acme Corp")
        notebook = await Notebook.objects.acreate(
            team=self.team,
            created_by=self.user,
            last_modified_by=self.user,
            visibility=Notebook.Visibility.INTERNAL,
            title="Q3 kickoff recap",
        )
        await ResourceNotebook.objects.acreate(notebook=notebook, account=account)

        result = await AccountContext(team=self.team, user=self.user, account_id=str(account.id)).execute_and_format()

        assert "### Saved notes" in result
        assert "Q3 kickoff recap" in result
        assert notebook.short_id in result

    async def test_analysis_connected_when_group_resolves(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        with (
            patch.object(AccountContext, "_account_group_type_index", return_value=2),
            patch("ee.hogai.context.account.context.get_group_by_key", return_value=MagicMock()) as mock_lookup,
        ):
            result = await AccountContext(
                team=self.team, user=self.user, account_id=str(account.id)
            ).execute_and_format()

        mock_lookup.assert_called_once()
        assert "<account_analysis_context>" in result
        assert "group type index 2" in result
        assert 'group key "acme-1"' in result

    async def test_billing_insights_clause_lists_configured_short_ids(self):
        # Pins the real short_ids: fails if the constants are deleted, emptied, or changed by accident.
        assert (
            AccountContext(team=self.team, user=self.user)._billing_insights_clause()
            == " (Usage insight short ids: fiJDsKLp; Spend insight short ids: o4I9sdFE, Tjo4bsux)"
        )

    async def test_analysis_not_configured_when_group_type_index_missing(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        with (
            patch.object(AccountContext, "_account_group_type_index", return_value=None),
            patch("ee.hogai.context.account.context.get_group_by_key") as mock_lookup,
        ):
            result = await AccountContext(
                team=self.team, user=self.user, account_id=str(account.id)
            ).execute_and_format()

        mock_lookup.assert_not_called()
        assert "isn't connected to a group type" in result

    async def test_analysis_no_external_id_when_account_unlinked(self):
        account = await self._create_account(name="Acme Corp")

        with (
            patch.object(AccountContext, "_account_group_type_index", return_value=2),
            patch("ee.hogai.context.account.context.get_group_by_key") as mock_lookup,
        ):
            result = await AccountContext(
                team=self.team, user=self.user, account_id=str(account.id)
            ).execute_and_format()

        mock_lookup.assert_not_called()
        assert "has no external ID" in result

    async def test_analysis_group_not_found(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        with (
            patch.object(AccountContext, "_account_group_type_index", return_value=2),
            patch("ee.hogai.context.account.context.get_group_by_key", return_value=None),
        ):
            result = await AccountContext(
                team=self.team, user=self.user, account_id=str(account.id)
            ).execute_and_format()

        assert "doesn't match any known group" in result

    async def test_reads_configured_group_type_index(self):
        team = MagicMock()
        team.customer_analytics_config.account_group_type_index = 7

        assert AccountContext(team=team, user=self.user)._account_group_type_index() == 7

    async def test_group_type_index_none_when_config_missing(self):
        class _TeamWithoutConfig:
            @property
            def customer_analytics_config(self):
                raise ObjectDoesNotExist

        assert AccountContext(team=_TeamWithoutConfig(), user=self.user)._account_group_type_index() is None  # type: ignore[arg-type]
