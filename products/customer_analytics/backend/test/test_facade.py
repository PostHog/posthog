from posthog.test.base import BaseTest

from posthog.models.tag import Tag
from posthog.models.tagged_item import TaggedItem
from posthog.rbac.user_access_control import UserAccessControl

from products.customer_analytics.backend.facade import (
    api as facade,
    contracts,
)
from products.customer_analytics.backend.models.account import AccountAssignment, AccountProperties
from products.customer_analytics.backend.test.factories import create_account
from products.notebooks.backend.models import Notebook, ResourceNotebook


class TestCustomerAnalyticsFacade(BaseTest):
    def _uac(self) -> UserAccessControl:
        return UserAccessControl(user=self.user, team=self.team)

    def test_get_account_returns_contract_with_properties(self):
        account = create_account(
            team_id=self.team.id,
            name="Acme Corp",
            external_id="acme-123",
            _properties=AccountProperties(
                csm=AccountAssignment(id=self.user.id, email=self.user.email),
                stripe_customer_id="cus_1",
            ).model_dump(mode="json"),
        )

        result = facade.get_account(self.team.id, account_id=str(account.id))

        assert isinstance(result, contracts.Account)
        assert result.id == account.id
        assert result.team_id == self.team.id
        assert result.external_id == "acme-123"
        assert result.name == "Acme Corp"
        assert result.properties.csm == contracts.AccountAssignment(id=self.user.id, email=self.user.email)
        assert result.properties.stripe_customer_id == "cus_1"

    def test_get_account_by_external_id_and_missing(self):
        create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-123")

        assert facade.get_account(self.team.id, external_id="acme-123") is not None
        assert facade.get_account(self.team.id, external_id="nope") is None
        assert facade.get_account(self.team.id, account_id="not-a-uuid") is None
        assert facade.get_account(self.team.id) is None

    def test_get_account_context_data_bundles_tags_and_notes(self):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-123")
        tag = Tag.objects.create(name="enterprise", team_id=self.team.id)
        TaggedItem.objects.create(tag=tag, account=account)
        notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            title="Q3 recap",
            visibility=Notebook.Visibility.INTERNAL,
        )
        ResourceNotebook.objects.create(notebook=notebook, account=account)

        data = facade.get_account_context_data(self.team.id, account_id=str(account.id))

        assert isinstance(data, contracts.AccountContextData)
        assert data.name == "Acme Corp"
        assert data.tags == ["enterprise"]
        assert data.notes == [contracts.AccountNote(title="Q3 recap", short_id=notebook.short_id)]

    def test_get_account_context_data_missing(self):
        assert facade.get_account_context_data(self.team.id, external_id="missing") is None

    def test_search_accounts_matches_name_and_external_id(self):
        create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-123")
        create_account(team_id=self.team.id, name="Globex", external_id="globex-9")

        rows, count = facade.search_accounts(self.team.id, "acme", self._uac(), limit=10)

        assert count == 1
        assert [r.name for r in rows] == ["Acme Corp"]
        assert isinstance(rows[0], contracts.AccountRef)
        assert rows[0].id == str(rows[0].id)

    def test_list_accounts_newest_first_with_count(self):
        create_account(team_id=self.team.id, name="First")
        create_account(team_id=self.team.id, name="Second")

        rows, count = facade.list_accounts(self.team.id, offset=0, limit=10, user_access_control=self._uac())

        assert count == 2
        assert {r.name for r in rows} == {"First", "Second"}
