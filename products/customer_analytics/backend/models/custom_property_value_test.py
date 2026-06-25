from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from products.customer_analytics.backend.models import Account, CustomPropertyDefinition, CustomPropertyValue
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin


class CustomPropertyValueTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.account = Account.objects.create(team=self.team, name="Acme")
        self.definition = CustomPropertyDefinition.objects.create(team=self.team, name="Seats")

    def _create(self, definition: CustomPropertyDefinition | None = None, **kwargs) -> CustomPropertyValue:
        return CustomPropertyValue.objects.create(
            team=self.team, account=self.account, definition=definition or self.definition, **kwargs
        )

    @parameterized.expand(
        [
            ("str", "value_str", "enterprise"),
            ("bool", "value_bool", True),
            ("num_decimal", "value_num", 9.99),
            ("num_integer", "value_num", 12),
            ("datetime", "value_datetime", datetime(2026, 1, 1, tzinfo=UTC)),
        ]
    )
    def test_single_value_of_each_type_persists(self, _name, field, value):
        definition = CustomPropertyDefinition.objects.create(team=self.team, name=f"def-{_name}")

        instance = self._create(definition=definition, **{field: value})
        instance.refresh_from_db()

        assert getattr(instance, field) == value

    def test_rejects_no_value_set(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                self._create()

    def test_rejects_multiple_values_set(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                self._create(value_str="enterprise", value_num=1.0)

    def test_rejects_second_active_value_for_same_definition(self):
        self._create(value_str="first")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                self._create(value_str="second")

    def test_soft_deleting_active_value_allows_a_new_one_and_keeps_history(self):
        first = self._create(value_str="first")
        first.is_deleted = True
        first.save()

        second = self._create(value_str="second")

        rows = CustomPropertyValue.objects.filter(account=self.account, definition=self.definition)
        assert rows.count() == 2
        assert rows.get(is_deleted=False) == second

    def test_multiple_deleted_values_coexist(self):
        for value in ("v1", "v2", "v3"):
            row = self._create(value_str=value)
            row.is_deleted = True
            row.save()

        assert (
            CustomPropertyValue.objects.filter(
                account=self.account, definition=self.definition, is_deleted=True
            ).count()
            == 3
        )
