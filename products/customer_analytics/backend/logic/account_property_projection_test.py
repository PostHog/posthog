from posthog.test.base import BaseTest
from unittest.mock import patch

from products.customer_analytics.backend.logic.account_property_projection import account_property_projection
from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_custom_property_definition, create_saved_query
from products.warehouse_sources.backend.facade.hooks import saved_query_binding, schema_binding


class AccountPropertyProjectionTest(TeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.saved_query = create_saved_query(team_id=self.team.id)
        flag_patch = patch(
            "products.customer_analytics.backend.logic.account_property_projection.account_property_staging_enabled",
            return_value=True,
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def _source(self, name: str, key_column: str, source_column: str, *, is_enabled: bool = True) -> None:
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name=name,
            target_type=TargetType.ACCOUNT.value,
        )
        CustomPropertySource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            definition=definition,
            saved_query=self.saved_query,
            key_column=key_column,
            source_column=source_column,
            is_enabled=is_enabled,
        )

    def test_projects_key_and_value_columns_for_enabled_account_sources(self) -> None:
        self._source("MRR", "organization_id", "mrr")
        self._source("Plan", "account_id", "plan")
        self._source("Disabled", "organization_id", "disabled", is_enabled=False)

        projection = account_property_projection(self.team.id, saved_query_binding(self.saved_query.id))

        assert projection is not None
        assert {item.key_column: item.columns for item in projection} == {
            "organization_id": frozenset({"organization_id", "mrr"}),
            "account_id": frozenset({"account_id", "plan"}),
        }

    def test_returns_none_for_schema_bindings_and_views_without_sources(self) -> None:
        assert account_property_projection(self.team.id, schema_binding("019f0000-0000-7000-8000-000000000001")) is None
        assert account_property_projection(self.team.id, saved_query_binding(self.saved_query.id)) is None
