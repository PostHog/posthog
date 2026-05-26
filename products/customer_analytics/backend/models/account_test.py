from contextlib import AbstractContextManager

import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.customer_analytics.backend.models import Account, TeamCustomerAnalyticsConfig
from products.customer_analytics.backend.models.account import AccountAssignment, AccountProperties


class _AccountTeamScopedTestMixin:
    """Wraps setUp/tearDown with team_scope so test-body queries to Account find a scope."""

    _team_scope_cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._team_scope_cm = cm

    def tearDown(self) -> None:
        if self._team_scope_cm is not None:
            try:
                self._team_scope_cm.__exit__(None, None, None)
            finally:
                self._team_scope_cm = None
        super().tearDown()  # type: ignore[misc]


class AccountPropertiesValidationTest(_AccountTeamScopedTestMixin, BaseTest):
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


class AccountExternalIdUniquenessTest(_AccountTeamScopedTestMixin, BaseTest):
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


class TeamCustomerAnalyticsConfigDriftPolicyTest(_AccountTeamScopedTestMixin, BaseTest):
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
