import json

from posthog.test.base import BaseTest

from posthog.hogql.database.lazy_join_tags import DATA_WAREHOUSE, FOREIGN_KEY
from posthog.hogql.database.models import LazyJoin
from posthog.hogql.database.warehouse_join_resolvers import data_warehouse_resolver_params
from posthog.hogql.errors import ResolutionError


class TestLazyJoinResolvers(BaseTest):
    def test_data_warehouse_join_carries_no_closure(self):
        lazy_join = LazyJoin(
            from_field=["id"],
            to_field=["account_id"],
            join_table="stripe.accounts",
            resolver=DATA_WAREHOUSE,
            resolver_params=data_warehouse_resolver_params(
                source_table_key="id",
                joining_table_key="account_id",
                joining_table_name="stripe.accounts",
            ),
        )

        assert lazy_join.join_function is None
        assert lazy_join.resolver == DATA_WAREHOUSE
        # The whole point: the join is described by plain JSON-able data, not a Python closure,
        # so the Database that holds it can be serialized and cached.
        encoded = json.dumps(lazy_join.resolver_params)
        assert "stripe.accounts" in encoded

    def test_foreign_key_join_carries_no_closure(self):
        lazy_join = LazyJoin(from_field=["account_id"], to_field=["id"], join_table="accounts", resolver=FOREIGN_KEY)

        assert lazy_join.join_function is None
        assert lazy_join.resolver == FOREIGN_KEY

    def test_resolver_params_applies_overrides(self):
        params = data_warehouse_resolver_params(
            source_table_key="id",
            joining_table_key="account_id",
            joining_table_name="events",
            override_source_table_key="person.id",
            override_join_type="INNER JOIN",
        )

        assert params["source_table_key"] == "person.id"
        assert params["join_type"] == "INNER JOIN"
        assert params["configuration"] == {}

    def test_unknown_resolver_raises(self):
        lazy_join = LazyJoin(from_field=["id"], join_table="x", resolver="does_not_exist")
        with self.assertRaises(ValueError):
            lazy_join.resolve_join_to_add(None, None, None)  # type: ignore[arg-type]

    def test_lazy_join_without_resolver_or_function_raises(self):
        lazy_join = LazyJoin(from_field=["id"], join_table="x")
        with self.assertRaises(ResolutionError):
            lazy_join.resolve_join_to_add(None, None, None)  # type: ignore[arg-type]
