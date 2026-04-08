import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_warehouse.backend.data_load.source_templates import _revenue_view_name, database_operations
from products.data_warehouse.backend.models.join import DataWarehouseJoin

pytestmark = [pytest.mark.django_db]


class TestRevenueViewName(BaseTest):
    @parameterized.expand(
        [
            ("", "stripe.customer_revenue_view"),
            ("my_prefix_", "stripe.my_prefix.customer_revenue_view"),
            ("org_123_", "stripe.org_123.customer_revenue_view"),
        ]
    )
    def test_revenue_view_name(self, table_prefix, expected):
        assert _revenue_view_name(table_prefix) == expected


class TestDatabaseOperations(BaseTest):
    def _get_active_joins(self):
        return DataWarehouseJoin.objects.filter(team=self.team).exclude(deleted=True)

    def test_creates_all_joins(self):
        database_operations(self.team.pk, "")

        joins = self._get_active_joins()
        assert joins.count() == 3

        revenue_join = joins.get(source_table_name="stripe.customer_revenue_view")
        assert revenue_join.source_table_key == "JSONExtractString(metadata, 'posthog_person_distinct_id')"
        assert revenue_join.joining_table_name == "persons"
        assert revenue_join.joining_table_key == "pdi.distinct_id"
        assert revenue_join.field_name == "persons"

        customer_join = joins.get(joining_table_name="stripe_customer")
        assert customer_join.source_table_name == "persons"
        assert customer_join.source_table_key == "properties.email"
        assert customer_join.joining_table_key == "email"
        assert customer_join.field_name == "stripe_customer"

        invoice_join = joins.get(joining_table_name="stripe_invoice")
        assert invoice_join.source_table_name == "persons"
        assert invoice_join.source_table_key == "properties.email"
        assert invoice_join.joining_table_key == "customer_email"
        assert invoice_join.field_name == "stripe_invoice"

    @parameterized.expand(["my_prefix_", "org_123_"])
    def test_applies_table_prefix(self, prefix):
        database_operations(self.team.pk, prefix)

        joins = self._get_active_joins()
        assert joins.count() == 3
        assert joins.filter(
            joining_table_name=f"{prefix}stripe_customer", field_name=f"{prefix}stripe_customer"
        ).exists()
        assert joins.filter(joining_table_name=f"{prefix}stripe_invoice", field_name=f"{prefix}stripe_invoice").exists()
        assert joins.filter(source_table_name=_revenue_view_name(prefix)).exists()

    def test_idempotent(self):
        database_operations(self.team.pk, "")
        database_operations(self.team.pk, "")

        assert self._get_active_joins().count() == 3

    def test_skips_existing_creates_missing(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="stripe_customer",
            joining_table_key="email",
            field_name="stripe_customer",
        )

        database_operations(self.team.pk, "")

        assert self._get_active_joins().count() == 3

    def test_recreates_after_soft_delete(self):
        database_operations(self.team.pk, "")
        customer_join = self._get_active_joins().get(joining_table_name="stripe_customer")
        customer_join.soft_delete()

        database_operations(self.team.pk, "")

        assert self._get_active_joins().count() == 3
        assert DataWarehouseJoin.objects.filter(
            team=self.team, joining_table_name="stripe_customer", deleted=True
        ).exists()
