from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, User
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

        data = facade.get_account_context_data(
            self.team.id, account_id=str(account.id), user_access_control=self._uac()
        )

        assert isinstance(data, contracts.AccountContextData)
        assert data.name == "Acme Corp"
        assert data.tags == ["enterprise"]
        assert data.notes == [contracts.AccountNote(title="Q3 recap", short_id=notebook.short_id)]

    def test_get_account_context_data_missing(self):
        assert (
            facade.get_account_context_data(self.team.id, external_id="missing", user_access_control=self._uac())
            is None
        )

    def test_get_account_context_data_denied_object_level_returns_none(self):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-123")
        uac = MagicMock()
        uac.check_access_level_for_resource.return_value = True
        uac.filter_queryset_by_access_level.side_effect = lambda qs: qs.none()

        assert (
            facade.get_account_context_data(self.team.id, account_id=str(account.id), user_access_control=uac) is None
        )

    def test_get_account_context_data_denied_resource_level_returns_none(self):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-123")
        uac = MagicMock()
        uac.check_access_level_for_resource.return_value = False

        assert (
            facade.get_account_context_data(self.team.id, account_id=str(account.id), user_access_control=uac) is None
        )

    def test_search_accounts_matches_name_and_external_id(self):
        create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-123")
        create_account(team_id=self.team.id, name="Globex", external_id="globex-9")

        rows, count = facade.search_accounts(self.team.id, "acme", self._uac(), limit=10)

        assert count == 1
        assert [r.name for r in rows] == ["Acme Corp"]
        assert isinstance(rows[0], contracts.AccountRef)
        assert isinstance(rows[0].id, str)

    def test_list_accounts_newest_first_with_count(self):
        create_account(team_id=self.team.id, name="First")
        create_account(team_id=self.team.id, name="Second")

        rows, count = facade.list_accounts(self.team.id, offset=0, limit=10, user_access_control=self._uac())

        assert count == 2
        assert {r.name for r in rows} == {"First", "Second"}

    # -- External account API (CDP worker) --------------------------------

    def test_get_external_account_returns_verbatim_shape(self):
        account = create_account(
            team_id=self.team.id,
            name="Acme Corp",
            external_id="acme-1",
            _properties=AccountProperties(
                csm=AccountAssignment(id=self.user.id, email=self.user.email),
            ).model_dump(mode="json"),
        )
        tag = Tag.objects.create(name="enterprise", team_id=self.team.id)
        TaggedItem.objects.create(tag=tag, account=account)

        result = facade.get_external_account(self.team.id, "acme-1")

        assert isinstance(result, contracts.ExternalAccount)
        assert result.id == str(account.id)
        assert result.external_id == "acme-1"
        assert result.name == "Acme Corp"
        assert result.tags == ["enterprise"]
        assert result.properties == account.properties.model_dump(mode="json")
        assert result.properties["csm"] == {"id": self.user.id, "email": self.user.email}

    def test_get_external_account_missing_and_other_team(self):
        create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        other_team = Organization.objects.bootstrap(None, name="Other")[2]

        assert facade.get_external_account(self.team.id, "nope") is None
        assert facade.get_external_account(other_team.id, "acme-1") is None

    def test_update_external_account_not_found_returns_not_found(self):
        result = facade.update_external_account(
            self.team.id, "missing", role_assignments={}, tags=None, tags_mode="add"
        )
        assert result.account is None
        assert result.error == contracts.ExternalAccountUpdateError.NOT_FOUND

    def test_update_external_account_assigns_role_and_resolves_email(self):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")

        result = facade.update_external_account(
            self.team.id, "acme-1", role_assignments={"csm": self.user.id}, tags=None, tags_mode="add"
        )

        assert result.error is None
        assert result.account is not None
        assert result.account.properties["csm"] == {"id": self.user.id, "email": self.user.email}
        account.refresh_from_db()
        assert account.properties.csm == AccountAssignment(id=self.user.id, email=self.user.email)

    def test_update_external_account_clears_role_with_none(self):
        account = create_account(
            team_id=self.team.id,
            name="Acme Corp",
            external_id="acme-1",
            _properties=AccountProperties(
                csm=AccountAssignment(id=self.user.id, email=self.user.email),
            ).model_dump(mode="json"),
        )

        result = facade.update_external_account(
            self.team.id, "acme-1", role_assignments={"csm": None}, tags=None, tags_mode="add"
        )

        assert result.account is not None
        assert result.account.properties["csm"] is None
        account.refresh_from_db()
        assert account.properties.csm is None

    def test_update_external_account_preserves_unmentioned_properties(self):
        account = create_account(
            team_id=self.team.id,
            name="Acme Corp",
            external_id="acme-1",
            _properties=AccountProperties(stripe_customer_id="cus_123").model_dump(mode="json"),
        )

        facade.update_external_account(
            self.team.id, "acme-1", role_assignments={"csm": self.user.id}, tags=None, tags_mode="add"
        )

        account.refresh_from_db()
        assert account.properties.stripe_customer_id == "cus_123"
        assert account.properties.csm == AccountAssignment(id=self.user.id, email=self.user.email)

    def test_update_external_account_rejects_non_member(self):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        outsider = User.objects.create_and_join(Organization.objects.create(name="Outsiders"), "out@example.com", None)

        result = facade.update_external_account(
            self.team.id, "acme-1", role_assignments={"csm": outsider.id}, tags=None, tags_mode="add"
        )

        assert result.account is None
        assert result.error == contracts.ExternalAccountUpdateError.USER_NOT_IN_ORGANIZATION
        assert result.error_field == "csm"
        account.refresh_from_db()
        assert account.properties.csm is None

    def test_update_external_account_invalid_properties(self):
        create_account(
            team_id=self.team.id,
            name="Acme Corp",
            external_id="acme-1",
            _properties={"not_a_real_property": "x"},
        )

        result = facade.update_external_account(
            self.team.id, "acme-1", role_assignments={"csm": self.user.id}, tags=None, tags_mode="add"
        )

        assert result.account is None
        assert result.error == contracts.ExternalAccountUpdateError.INVALID_PROPERTIES

    def test_update_external_account_tag_modes(self):
        create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")

        added = facade.update_external_account(
            self.team.id, "acme-1", role_assignments={}, tags=["enterprise"], tags_mode="add"
        )
        assert added.account is not None and added.account.tags == ["enterprise"]

        added_more = facade.update_external_account(
            self.team.id, "acme-1", role_assignments={}, tags=["priority"], tags_mode="add"
        )
        assert added_more.account is not None and added_more.account.tags == ["enterprise", "priority"]

        replaced = facade.update_external_account(
            self.team.id, "acme-1", role_assignments={}, tags=["only"], tags_mode="set"
        )
        assert replaced.account is not None and replaced.account.tags == ["only"]

        removed = facade.update_external_account(
            self.team.id, "acme-1", role_assignments={}, tags=["only"], tags_mode="remove"
        )
        assert removed.account is not None and removed.account.tags == []

    def test_update_external_account_rolls_back_role_when_tags_fail(self):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")

        with patch(
            "products.customer_analytics.backend.facade.api._apply_external_tags",
            side_effect=Exception("boom"),
        ):
            result = facade.update_external_account(
                self.team.id,
                "acme-1",
                role_assignments={"csm": self.user.id},
                tags=["enterprise"],
                tags_mode="add",
            )

        assert result.account is None
        assert result.error == contracts.ExternalAccountUpdateError.UPDATE_FAILED
        account.refresh_from_db()
        assert account.properties.csm is None
