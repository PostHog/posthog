from datetime import datetime, timedelta, UTC

import pytest
from freezegun import freeze_time

from posthog.models.insight import Insight
from posthog.models.product_intent.product_intent import (
    ProductIntent,
    calculate_product_activation,
)
from posthog.test.base import BaseTest


class TestProductIntent(BaseTest):
    def setUp(self):
        super().setUp()
        self.product_intent = ProductIntent.objects.create(team=self.team, product_type="data_warehouse")

    def test_str_representation(self):
        self.assertEqual(str(self.product_intent), f"{self.team.name} - data_warehouse")

    def test_unique_constraint(self):
        # Test that we can't create duplicate product intents for same team/product
        with pytest.raises(Exception):
            ProductIntent.objects.create(team=self.team, product_type="data_warehouse")

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_activated_data_warehouse_with_valid_query(self):
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}}
        )

        self.assertTrue(self.product_intent.has_activated_data_warehouse())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_activated_data_warehouse_with_excluded_table(self):
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM events"}}
        )

        self.assertFalse(self.product_intent.has_activated_data_warehouse())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_activated_data_warehouse_with_old_insight(self):
        with freeze_time("2024-05-15T12:00:00Z"):  # Before June 1st, 2024
            Insight.objects.create(
                team=self.team,
                query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}},
            )

        self.assertFalse(self.product_intent.has_activated_data_warehouse())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_check_and_update_activation_sets_activated_at(self):
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}}
        )

        self.assertIsNone(self.product_intent.activated_at)
        self.product_intent.check_and_update_activation()
        self.product_intent.refresh_from_db()
        assert self.product_intent.activated_at == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

    @freeze_time("2024-06-15T12:00:00Z")
    def test_calculate_product_activation_task(self):
        # Create an insight that should trigger activation
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}}
        )

        calculate_product_activation(self.team.id)

        self.product_intent.refresh_from_db()
        assert self.product_intent.activated_at == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

    def test_calculate_product_activation_respects_check_interval(self):
        # Set last checked time to recent
        self.product_intent.activation_last_checked_at = datetime.now(tz=UTC)
        self.product_intent.save()

        calculate_product_activation(self.team.id, only_calc_if_days_since_last_checked=1)

        self.product_intent.refresh_from_db()
        self.assertIsNone(self.product_intent.activated_at)

    @freeze_time("2024-06-15T12:00:00Z")
    def test_calculate_product_activation_skips_activated_products(self):
        # Set product as already activated
        self.product_intent.activated_at = datetime.now(tz=UTC)
        self.product_intent.save()

        with freeze_time(datetime.now(tz=UTC) + timedelta(days=2)):
            calculate_product_activation(self.team.id)
            self.product_intent.refresh_from_db()
            assert self.product_intent.activated_at == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
