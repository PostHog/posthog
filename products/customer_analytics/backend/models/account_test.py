from typing import cast

import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, models, transaction
from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.customer_analytics.backend.models import Account, TeamCustomerAnalyticsConfig
from products.customer_analytics.backend.models.account import AccountProperties
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin

LEGACY_ROLE_PROPERTIES = {
    "csm": {"id": 1, "email": "csm@example.com"},
    "account_executive": None,
    "account_owner": {"id": 2, "email": "owner@example.com"},
}


class AccountPropertiesValidationTest(TeamScopedTestMixin, BaseTest):
    def test_rejects_unknown_keys(self):
        with pytest.raises(PydanticValidationError):
            AccountProperties.model_validate({"unknown_field": "x"})

    def test_setter_validates_dict_input(self):
        account = Account.objects.create(team=self.team, name="Bad input")

        with pytest.raises(PydanticValidationError):
            account.properties = {"unknown_field": "x"}

    def test_legacy_role_keys_in_stored_row_stripped_on_read(self):
        account = Account.objects.create(
            team=self.team,
            name="Legacy row",
            _properties={**LEGACY_ROLE_PROPERTIES, "stripe_customer_id": "cus_1"},
        )

        props = account.properties
        assert props.stripe_customer_id == "cus_1"
        assert not set(LEGACY_ROLE_PROPERTIES) & set(props.model_dump())

    def test_legacy_role_keys_stripped_by_setter(self):
        account = Account.objects.create(team=self.team, name="Legacy write")

        account.properties = {**LEGACY_ROLE_PROPERTIES, "stripe_customer_id": "cus_1"}

        assert not set(LEGACY_ROLE_PROPERTIES) & set(account._properties)
        assert account._properties["stripe_customer_id"] == "cus_1"

    def test_legacy_role_keys_stripped_by_manager_create(self):
        account = Account.objects.create_account(
            team=self.team,
            name="Legacy create",
            properties={**LEGACY_ROLE_PROPERTIES, "stripe_customer_id": "cus_1"},
        )

        assert account._properties == {"stripe_customer_id": "cus_1"}


class AccountExternalIdUniquenessTest(TeamScopedTestMixin, BaseTest):
    def test_duplicate_external_id_within_team_rejected(self):
        Account.objects.create(team=self.team, name="First", external_id="acme")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Account.objects.create(team=self.team, name="Second", external_id="acme")

    def test_same_external_id_allowed_across_teams(self):
        other_team = Team.objects.create(organization=self.organization)
        with team_scope(other_team.id):
            Account.objects.create(team=other_team, name="Other team", external_id="acme")

        account = Account.objects.create(team=self.team, name="Same key, different team", external_id="acme")

        assert account.external_id == "acme"

    def test_multiple_null_external_ids_allowed_within_team(self):
        first = Account.objects.create(team=self.team, name="No group A")
        second = Account.objects.create(team=self.team, name="No group B")

        assert first.external_id is None
        assert second.external_id is None


class TeamCustomerAnalyticsConfigDriftPolicyTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.config = TeamCustomerAnalyticsConfig.objects.get(team=self.team)

    @parameterized.expand(
        [
            # Changing an already-set index while accounts exist is drift, and is blocked.
            ("drift_blocked_when_accounts_exist", 0, True, 1, True),
            # Changing the index is harmless, and allowed, while no accounts exist.
            ("drift_allowed_when_no_accounts_exist", 0, False, 1, False),
            # Setting the index for the first time (it was never set) is not drift,
            # so it is allowed even when accounts already exist.
            ("first_time_set_allowed_when_accounts_exist", None, True, 2, False),
        ]
    )
    def test_account_group_type_index_drift_policy(self, _name, initial_index, create_account, new_index, should_block):
        # `update()` skips the pre_save signal, so the policy does not fire on the fixture itself.
        TeamCustomerAnalyticsConfig.objects.filter(pk=self.config.pk).update(account_group_type_index=initial_index)
        if create_account:
            Account.objects.create(team=self.team, name="Existing")
        self.config.refresh_from_db()

        self.config.account_group_type_index = new_index
        if should_block:
            with pytest.raises(DjangoValidationError):
                self.config.save()
        else:
            self.config.save()
            self.config.refresh_from_db()
            assert self.config.account_group_type_index == new_index


class AccountManagerWriteTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            email="mgr@example.com", password=None, first_name="Mgr", is_email_verified=True
        )

    def test_update_account_replaces_properties_wholesale(self):
        account = Account.objects.create_account(
            team=self.team,
            created_by=self.user,
            name="Acme",
            properties={"hubspot_deal_id": "deal_1"},
        )
        Account.objects.update_account(account, properties={"stripe_customer_id": "cus_123"})
        account.refresh_from_db()
        assert account.properties.hubspot_deal_id is None
        assert account.properties.stripe_customer_id == "cus_123"

    def test_update_account_leaves_properties_untouched_when_not_passed(self):
        account = Account.objects.create_account(
            team=self.team,
            created_by=self.user,
            name="Acme",
            properties={"stripe_customer_id": "cus_123"},
        )

        Account.objects.update_account(account, name="Renamed")

        account.refresh_from_db()
        assert account.name == "Renamed"
        assert account.properties.stripe_customer_id == "cus_123"

    def test_update_account_updates_name_and_external_id(self):
        account = Account.objects.create_account(team=self.team, created_by=self.user, name="Old")
        Account.objects.update_account(account, name="New", external_id="acme-1")
        account.refresh_from_db()
        assert account.name == "New"
        assert account.external_id == "acme-1"


class AccountManagerCapToFieldLengthTest(SimpleTestCase):
    @parameterized.expand([("name",), ("external_id",)])
    def test_caps_value_to_field_max_length(self, field_name):
        max_length = cast(models.CharField, Account._meta.get_field(field_name)).max_length
        assert max_length is not None
        result = Account.objects._cap_to_field_length(field_name, "x" * (max_length + 50))
        assert result == "x" * max_length

    def test_leaves_value_within_limit_unchanged(self):
        assert Account.objects._cap_to_field_length("name", "Acme") == "Acme"
