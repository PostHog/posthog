# The facade owns the PostgresTable defs that core exposes as `system.accounts`,
# `system.custom_property_definitions`, and `system.accounts.custom_properties`. Core's own
# system-table suite is skipped on this product's CI shard by the isolation contract-check,
# so this guard lives in-product: it fails here if a model column is renamed/dropped without
# updating facade/hogql.py, catching the drift on the shard that actually runs for model changes.
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.database.models import ExpressionField, LazyJoin, Table

from products.customer_analytics.backend.facade.hogql import (
    account_custom_property_values,
    accounts,
    custom_property_definitions,
)
from products.customer_analytics.backend.models import Account, CustomPropertyDefinition, CustomPropertyValue


class TestFacadeHogqlSystemTables(SimpleTestCase):
    @parameterized.expand(
        [
            ("accounts", accounts, Account),
            ("custom_property_definitions", custom_property_definitions, CustomPropertyDefinition),
            ("account_custom_property_values", account_custom_property_values, CustomPropertyValue),
        ]
    )
    def test_federated_columns_exist_on_model(self, _name, table, model):
        model_columns = {field.column for field in model._meta.concrete_fields}
        exposed_columns = {
            field.name for field in table.fields.values() if not isinstance(field, (ExpressionField, LazyJoin, Table))
        }
        missing = exposed_columns - model_columns
        assert not missing, (
            f"system.{table.name} exposes {sorted(missing)}, which no longer exist as columns on "
            f"{model.__name__}. Update the PostgresTable def in facade/hogql.py to match the model."
        )
