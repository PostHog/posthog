import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, _create_person

from parameterized import parameterized

from posthog.schema import CurrencyCode

from posthog.hogql.database.schema.test.base import RevenueAnalyticsTestBase
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from products.data_warehouse.backend.data_load.source_templates import database_operations
from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.revenue_analytics.backend.joins import get_customer_revenue_view_name

pytestmark = [pytest.mark.django_db]


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
        assert joins.filter(source_table_name=get_customer_revenue_view_name(prefix)).exists()

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


class TestCustomerRevenueViewPersonsJoin(RevenueAnalyticsTestBase):
    """Verify that the joins created by database_operations actually resolve
    when revenue analytics queries through them."""

    def setUp(self):
        super().setUp()
        self.create_sources()
        self.team.base_currency = CurrencyCode.GBP.value
        self.team.save()
        self.view_name = get_customer_revenue_view_name(self.source.prefix)

    def test_persons_join_resolves_on_customer_view(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person_cus_1"],
            properties={"marker": "found"},
        )

        database_operations(self.team.pk, self.source.prefix or "")

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select(
                    f"SELECT id, persons.properties.marker FROM {self.view_name}"
                    f" WHERE persons.properties.marker IS NOT NULL ORDER BY id"
                ),
                self.team,
                modifiers=self.MODIFIERS,
            )
        assert len(response.results) == 1
        assert response.results[0][0] == "cus_1"
        assert response.results[0][1] == "found"
