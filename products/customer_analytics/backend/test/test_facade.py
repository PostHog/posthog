from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.tag import Tag
from posthog.models.tagged_item import TaggedItem
from posthog.rbac.user_access_control import UserAccessControl

from products.customer_analytics.backend.facade import (
    api as facade,
    contracts,
)
from products.customer_analytics.backend.models import Account, CustomPropertyDefinition, CustomPropertySource
from products.customer_analytics.backend.models.account import AccountAssignment, AccountProperties
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_account
from products.notebooks.backend.models import Notebook, ResourceNotebook
from products.product_analytics.backend.models.insight import Insight


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


class TestCustomerAnalyticsCRUDFacade(BaseTest):
    """Parity coverage for the presentation-wave CRUD functions the account/journey/
    profile-config viewsets call."""

    def _uac(self) -> UserAccessControl:
        return UserAccessControl(user=self.user, team=self.team)

    def _create_account_input(self, **kwargs) -> contracts.CreateAccountInput:
        kwargs.setdefault("name", "Acme Corp")
        return contracts.CreateAccountInput(**kwargs)

    def _create(self, **kwargs) -> contracts.AccountView:
        return facade.create_account_for_view(
            team_id=self.team.id,
            team=self.team,
            input=self._create_account_input(**kwargs),
            organization_id=self.organization.id,
            user=self.user,
            was_impersonated=False,
        )

    # --- Account create/update/delete ---

    def test_create_account_returns_view_and_persists(self):
        view = self._create(name="Acme", external_id="acme-1", properties={"stripe_customer_id": "cus_1"})

        assert isinstance(view, contracts.AccountView)
        assert view.name == "Acme"
        assert view.external_id == "acme-1"
        assert view.properties == {"stripe_customer_id": "cus_1"}
        assert view.created_by == self.user.id
        stored = Account.objects.unscoped().get(id=str(view.id))
        assert stored.team_id == self.team.id
        assert stored.created_by_id == self.user.id

    def test_create_account_empty_properties_serializes_as_empty_dict(self):
        view = self._create(name="Bare")
        assert view.properties == {}

    def test_create_account_sets_tags(self):
        view = self._create(name="Tagged", tags=["enterprise", "priority"])
        account = Account.objects.unscoped().get(id=str(view.id))
        assert sorted(TaggedItem.objects.filter(account=account).values_list("tag__name", flat=True)) == [
            "enterprise",
            "priority",
        ]

    def test_create_account_duplicate_external_id_raises_conflict(self):
        self._create(name="First", external_id="dup")
        with self.assertRaises(facade.AccountConflictError):
            self._create(name="Second", external_id="dup")

    def test_create_account_invalid_properties_raises_validation_error(self):
        with self.assertRaises(facade.AccountPropertiesValidationError) as ctx:
            self._create(name="Bad", properties={"unknown_field": "x"})
        assert ctx.exception.messages  # non-empty field-error list

    def test_create_account_logs_activity(self):
        view = self._create(name="Logged")
        log = ActivityLog.objects.get(team_id=self.team.id, scope="Account", activity="created")
        assert log.item_id == str(view.id)

    def test_update_account_changes_name_and_tags(self):
        view = self._create(name="Before", tags=["old"])
        updated = facade.update_account_for_view(
            team_id=self.team.id,
            account_id=str(view.id),
            input=contracts.UpdateAccountInput(name="After", tags=["new"]),
            user_access_control=self._uac(),
            required_level="editor",
            organization_id=self.organization.id,
            user=self.user,
            was_impersonated=False,
        )
        assert updated.name == "After"
        assert updated.tags == ["new"]

    def test_update_account_unknown_raises_does_not_exist(self):
        with self.assertRaises(facade.Account_DoesNotExist):
            facade.update_account_for_view(
                team_id=self.team.id,
                account_id="00000000-0000-0000-0000-000000000000",
                input=contracts.UpdateAccountInput(name="x"),
                user_access_control=self._uac(),
                required_level="editor",
                organization_id=self.organization.id,
                user=self.user,
                was_impersonated=False,
            )

    def test_delete_account_removes_row(self):
        view = self._create(name="Doomed")
        facade.delete_account_for_view(
            team_id=self.team.id,
            account_id=str(view.id),
            user_access_control=self._uac(),
            required_level="editor",
            organization_id=self.organization.id,
            user=self.user,
            was_impersonated=False,
        )
        assert not Account.objects.unscoped().filter(id=str(view.id)).exists()

    def test_get_account_for_view_unknown_raises(self):
        with self.assertRaises(facade.Account_DoesNotExist):
            facade.get_account_for_view(
                team_id=self.team.id,
                account_id="00000000-0000-0000-0000-000000000000",
                user_access_control=self._uac(),
                required_level="viewer",
            )

    def test_list_accounts_for_view_filters_by_search(self):
        self._create(name="Acme Corp", external_id="acme-1")
        self._create(name="Globex", external_id="glx-9")
        page, count = facade.list_accounts_for_view(
            team_id=self.team.id, user_access_control=self._uac(), offset=0, limit=10, search="acme"
        )
        assert count == 1
        assert [a.name for a in page] == ["Acme Corp"]

    # --- CustomerJourney ---

    def test_create_journey_returns_view_and_logs(self):
        insight = Insight.objects.create(team=self.team)
        view = facade.create_customer_journey(
            team_id=self.team.id,
            insight_id=insight.id,
            name="Onboarding",
            description="desc",
            organization_id=self.organization.id,
            user=self.user,
            was_impersonated=False,
        )
        assert isinstance(view, contracts.CustomerJourneyView)
        assert view.insight == insight.id
        assert view.created_by == self.user.id
        assert ActivityLog.objects.filter(team_id=self.team.id, scope="CustomerJourney", activity="created").exists()

    def test_create_journey_duplicate_insight_raises_conflict(self):
        insight = Insight.objects.create(team=self.team)
        kwargs = {
            "team_id": self.team.id,
            "insight_id": insight.id,
            "description": None,
            "organization_id": self.organization.id,
            "user": self.user,
            "was_impersonated": False,
        }
        facade.create_customer_journey(name="First", **kwargs)
        with self.assertRaises(facade.CustomerJourneyConflictError):
            facade.create_customer_journey(name="Second", **kwargs)

    def test_insight_belongs_to_team(self):
        insight = Insight.objects.create(team=self.team)
        assert facade.insight_belongs_to_team(self.team.id, insight.id)
        assert not facade.insight_belongs_to_team(self.team.id, insight.id + 9999)

    # --- CustomerProfileConfig ---

    def test_profile_config_create_update_delete_with_activity(self):
        created = facade.create_customer_profile_config(
            team_id=self.team.id,
            scope="person",
            content={"a": 1},
            sidebar={},
            organization_id=self.organization.id,
            user=self.user,
            was_impersonated=False,
        )
        assert isinstance(created, contracts.CustomerProfileConfigView)
        assert created.scope == "person"
        assert ActivityLog.objects.filter(
            team_id=self.team.id, scope="CustomerProfileConfig", activity="created"
        ).exists()

        updated = facade.update_customer_profile_config(
            team_id=self.team.id,
            config_id=str(created.id),
            fields={"content": {"a": 2}},
            organization_id=self.organization.id,
            user=self.user,
            was_impersonated=False,
        )
        assert updated is not None and updated.content == {"a": 2}

        assert facade.delete_customer_profile_config(
            team_id=self.team.id,
            config_id=str(created.id),
            organization_id=self.organization.id,
            user=self.user,
            was_impersonated=False,
        )
        assert ActivityLog.objects.filter(
            team_id=self.team.id, scope="CustomerProfileConfig", activity="deleted"
        ).exists()

    def test_profile_config_update_unknown_returns_none(self):
        assert (
            facade.update_customer_profile_config(
                team_id=self.team.id,
                config_id="00000000-0000-0000-0000-000000000000",
                fields={"scope": "person"},
                organization_id=self.organization.id,
                user=self.user,
                was_impersonated=False,
            )
            is None
        )


class TestCustomPropertySourceFacade(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
        self.view = saved_query_model.objects.create(
            team=self.team, name="billing_view", columns={"org_id": {}, "mrr": {}}
        )
        self.definition = CustomPropertyDefinition.objects.create(team=self.team, name="MRR")

    def _create(self, **overrides):
        kwargs: dict = {
            "team_id": self.team.id,
            "definition_id": self.definition.id,
            "saved_query_id": self.view.id,
            "source_column": "mrr",
            "key_column": "org_id",
            "is_enabled": True,
            "user": self.user,
        }
        kwargs.update(overrides)
        return facade.create_custom_property_source(**kwargs)

    def test_create_returns_contract(self):
        result = self._create()

        assert isinstance(result, contracts.CustomPropertySourceView)
        assert result.definition == self.definition.id
        assert result.saved_query == self.view.id
        assert result.source_column == "mrr"
        assert result.is_enabled is True
        assert result.id is not None
        assert CustomPropertySource.objects.for_team(self.team.id).filter(id=result.id).exists()

    def test_create_rejects_saved_query_from_another_team(self):
        saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_view = saved_query_model.objects.create(team=other_team, name="other_view", columns={})

        with pytest.raises(facade.CustomPropertySourceValidationError):
            self._create(saved_query_id=other_view.id)

    def test_create_rejects_definition_from_another_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_definition = CustomPropertyDefinition.objects.create(team=other_team, name="Other MRR")

        with pytest.raises(facade.CustomPropertySourceValidationError):
            self._create(definition_id=other_definition.id)

    def test_create_rejects_second_source_for_same_definition(self):
        self._create()

        with pytest.raises(facade.CustomPropertySourceValidationError):
            self._create()

    def test_update_reenable_resets_failure_streak_and_clears_error(self):
        source = self._create()
        CustomPropertySource.objects.filter(id=source.id).update(
            is_enabled=False, consecutive_failures=5, last_sync_error="boom"
        )

        result = facade.update_custom_property_source(
            team_id=self.team.id, source_id=source.id, fields={"is_enabled": True}
        )
        assert result is not None

        assert result.is_enabled is True
        assert result.consecutive_failures == 0
        assert result.last_sync_error is None

    def test_update_returns_none_for_missing_source(self):
        result = facade.update_custom_property_source(
            team_id=self.team.id, source_id=str(uuid4()), fields={"is_enabled": False}
        )
        assert result is None

    def test_delete_removes_source(self):
        source = self._create()

        assert facade.delete_custom_property_source(team_id=self.team.id, source_id=source.id) is True
        assert not CustomPropertySource.objects.for_team(self.team.id).filter(id=source.id).exists()

    @parameterized.expand([("enabled", True, True), ("disabled", False, False)])
    def test_create_enqueues_initial_sync_only_when_enabled(self, _name, is_enabled, expect_enqueued):
        with patch.object(facade, "current_app") as mock_app, self.captureOnCommitCallbacks(execute=True):
            self._create(is_enabled=is_enabled)

        if expect_enqueued:
            mock_app.send_task.assert_called_once_with(
                "customer_analytics.process_custom_property_sync",
                kwargs={"team_id": self.team.id, "saved_query_id": str(self.view.id)},
            )
        else:
            mock_app.send_task.assert_not_called()

    def test_reenabling_a_source_enqueues_a_sync(self):
        source = self._create(is_enabled=False)

        with patch.object(facade, "current_app") as mock_app, self.captureOnCommitCallbacks(execute=True):
            facade.update_custom_property_source(team_id=self.team.id, source_id=source.id, fields={"is_enabled": True})

        mock_app.send_task.assert_called_once_with(
            "customer_analytics.process_custom_property_sync",
            kwargs={"team_id": self.team.id, "saved_query_id": str(self.view.id)},
        )

    @parameterized.expand(
        [
            ("noop", {}, False),
            ("already_enabled", {"is_enabled": True}, False),
            ("column_change", {"source_column": "org_id"}, True),
        ]
    )
    def test_update_enqueues_only_on_meaningful_change(self, _name, fields, expect_enqueued):
        source = self._create()

        with patch.object(facade, "current_app") as mock_app, self.captureOnCommitCallbacks(execute=True):
            facade.update_custom_property_source(team_id=self.team.id, source_id=source.id, fields=fields)

        if expect_enqueued:
            mock_app.send_task.assert_called_once()
        else:
            mock_app.send_task.assert_not_called()

    def test_external_batch_rejects_source_backed_definition(self):
        self._create()
        create_account(team_id=self.team.id, name="Acme", external_id="acme")

        result = facade.set_external_account_custom_properties(
            self.team.id, "acme", properties={str(self.definition.id): 100}
        )

        assert result.error == contracts.ExternalAccountCustomPropertiesError.SOURCE_MANAGED
        assert result.values is None

    def test_get_definition_carries_source(self):
        uac = UserAccessControl(user=self.user, team=self.team)
        view = facade.get_custom_property_definition(self.team.id, self.definition.id, user_access_control=uac)
        assert view is not None
        assert view.source is None

        source = self._create()
        view = facade.get_custom_property_definition(self.team.id, self.definition.id, user_access_control=uac)
        assert view is not None
        assert view.source is not None
        assert view.source.id == source.id
        assert view.source.source_column == "mrr"

    def test_manual_value_write_rejected_on_source_backed_definition(self):
        self._create()
        account = create_account(team_id=self.team.id, external_id="org_1")

        with pytest.raises(facade.CustomPropertyValueSourceManaged):
            facade.set_custom_property_value(self.team.id, account.id, self.definition.id, 42)
