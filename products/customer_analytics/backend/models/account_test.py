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
from products.customer_analytics.backend.models.account import AccountAssignment, AccountProperties
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin


class AccountPropertiesValidationTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            email="apv@example.com", password=None, first_name="APV", is_email_verified=True
        )

    def test_rejects_unknown_keys(self):
        with pytest.raises(PydanticValidationError):
            AccountProperties.model_validate({"unknown_field": "x"})

    def test_typed_property_round_trip_through_setter(self):
        account = Account.objects.create(team=self.team, name="Round-trip")
        account.properties = AccountProperties(
            csm=AccountAssignment(id=self.user.id, email=self.user.email),
        )
        account.save()
        account.refresh_from_db()

        props = account.properties
        assert isinstance(props, AccountProperties)
        assert props.csm == AccountAssignment(id=self.user.id, email=self.user.email)
        assert props.account_executive is None
        assert props.account_owner is None

    def test_setter_validates_dict_input(self):
        account = Account.objects.create(team=self.team, name="Bad input")

        with pytest.raises(PydanticValidationError):
            account.properties = {"unknown_field": "x"}


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
            properties={"csm": {"id": self.user.id, "email": self.user.email}},
        )
        Account.objects.update_account(account, properties={"stripe_customer_id": "cus_123"})
        account.refresh_from_db()
        assert account.properties.csm is None
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
