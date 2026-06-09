import uuid

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ObjectDoesNotExist

from asgiref.sync import sync_to_async

from posthog.api.tagged_item import set_tags_on_object

from products.customer_analytics.backend.models import Account
from products.notebooks.backend.models import Notebook, ResourceNotebook

from ee.hogai.context.account.context import AccountContext


class TestAccountContext(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    async def _create_account(self, **kwargs) -> Account:
        return await sync_to_async(Account.objects.unscoped().create)(team=self.team, **kwargs)

    async def test_aget_account_by_id(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        fetched = await AccountContext(team=self.team, account_id=str(account.id)).aget_account()

        assert fetched is not None
        assert fetched.id == account.id

    async def test_aget_account_by_external_id(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        fetched = await AccountContext(team=self.team, external_id="acme-1").aget_account()

        assert fetched is not None
        assert fetched.id == account.id

    async def test_aget_account_invalid_id_returns_none(self):
        assert await AccountContext(team=self.team, account_id="not-a-uuid").aget_account() is None

    async def test_execute_and_format_not_found(self):
        result = await AccountContext(team=self.team, account_id=str(uuid.uuid4())).execute_and_format()

        assert "was not found" in result

    async def test_format_includes_basics(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        assert "## Account: Acme Corp" in result
        assert str(account.id) in result
        assert "acme-1" in result

    async def test_format_external_id_not_set(self):
        account = await self._create_account(name="Acme Corp")

        result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        assert "**External ID:** Not set" in result

    async def test_format_includes_roles(self):
        account = await self._create_account(
            name="Acme Corp",
            _properties={"csm": {"id": 42, "email": "jane@acme.com"}},
        )

        result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        assert "### Roles" in result
        assert "CSM: jane@acme.com (user 42)" in result

    async def test_format_includes_external_system_ids(self):
        account = await self._create_account(name="Acme Corp", _properties={"stripe_customer_id": "cus_123"})

        result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        assert "### External-system ids" in result
        assert "Stripe customer id: cus_123" in result

    async def test_format_includes_tags(self):
        account = await self._create_account(name="Acme Corp")
        await sync_to_async(set_tags_on_object)(["enterprise", "priority"], account)

        result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

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

        result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        assert "### Saved notes" in result
        assert "Q3 kickoff recap" in result
        assert notebook.short_id in result

    async def test_analysis_connected_when_group_resolves(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        with (
            patch.object(AccountContext, "_account_group_type_index", return_value=2),
            patch("ee.hogai.context.account.context.get_group_by_key", return_value=MagicMock()) as mock_lookup,
        ):
            result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        mock_lookup.assert_called_once()
        assert "<account_analysis_context>" in result
        assert "group type index 2" in result
        assert 'group key "acme-1"' in result

    async def test_analysis_not_configured_when_group_type_index_missing(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        with (
            patch.object(AccountContext, "_account_group_type_index", return_value=None),
            patch("ee.hogai.context.account.context.get_group_by_key") as mock_lookup,
        ):
            result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        mock_lookup.assert_not_called()
        assert "isn't connected to a group type" in result

    async def test_analysis_no_external_id_when_account_unlinked(self):
        account = await self._create_account(name="Acme Corp")

        with (
            patch.object(AccountContext, "_account_group_type_index", return_value=2),
            patch("ee.hogai.context.account.context.get_group_by_key") as mock_lookup,
        ):
            result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        mock_lookup.assert_not_called()
        assert "has no external ID" in result

    async def test_analysis_group_not_found(self):
        account = await self._create_account(name="Acme Corp", external_id="acme-1")

        with (
            patch.object(AccountContext, "_account_group_type_index", return_value=2),
            patch("ee.hogai.context.account.context.get_group_by_key", return_value=None),
        ):
            result = await AccountContext(team=self.team, account_id=str(account.id)).format_account(account)

        assert "doesn't match any known group" in result

    async def test_reads_configured_group_type_index(self):
        team = MagicMock()
        team.customer_analytics_config.account_group_type_index = 7

        assert AccountContext(team=team)._account_group_type_index() == 7

    async def test_group_type_index_none_when_config_missing(self):
        class _TeamWithoutConfig:
            @property
            def customer_analytics_config(self):
                raise ObjectDoesNotExist

        assert AccountContext(team=_TeamWithoutConfig())._account_group_type_index() is None  # type: ignore[arg-type]
