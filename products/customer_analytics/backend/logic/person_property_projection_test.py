from posthog.test.base import BaseTest

from products.customer_analytics.backend.logic.person_property_projection import person_property_projection_columns
from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_custom_property_definition
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


class PersonPropertyProjectionTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Stripe"
        )
        self.schema = ExternalDataSchema.objects.create(team=self.team, source=source, name="users")

    def _person_source(self, name, key_column, column_property_map, *, is_enabled=True, schema=None):
        definition = create_custom_property_definition(
            team_id=self.team.id, name=name, target_type=TargetType.PERSON.value
        )
        return CustomPropertySource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            definition=definition,
            external_data_schema=schema or self.schema,
            key_column=key_column,
            column_property_map=column_property_map,
            is_enabled=is_enabled,
        )

    def test_returns_none_when_no_person_sources(self):
        assert person_property_projection_columns(self.team.id, self.schema.id) is None

    def test_unions_key_and_mapped_columns_across_enabled_person_sources(self):
        self._person_source("A", "distinct_id", {"plan": "plan_tier"})
        self._person_source("B", "user_id", {"seats": "seat_count", "region": "region"})

        columns = person_property_projection_columns(self.team.id, self.schema.id)

        assert columns == ["distinct_id", "plan", "region", "seats", "user_id"]

    def test_ignores_disabled_account_and_other_schema_sources(self):
        self._person_source("enabled", "distinct_id", {"plan": "plan_tier"})
        self._person_source("disabled", "other_id", {"col": "prop"}, is_enabled=False)

        # Account-target source on the same schema must not contribute.
        account_def = create_custom_property_definition(
            team_id=self.team.id, name="MRR", target_type=TargetType.ACCOUNT.value
        )
        CustomPropertySource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            definition=account_def,
            external_data_schema=self.schema,
            key_column="acct_id",
            column_property_map={"mrr": "mrr"},
        )

        columns = person_property_projection_columns(self.team.id, self.schema.id)

        assert columns == ["distinct_id", "plan"]
