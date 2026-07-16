from posthog.test.base import BaseTest
from unittest.mock import patch

from products.customer_analytics.backend.logic.person_property_projection import (
    person_property_projection,
    person_property_sync_sources,
)
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
        flag_patch = patch(
            "products.customer_analytics.backend.logic.person_property_projection.person_properties_flag_enabled",
            return_value=True,
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

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

    def _projected(self):
        projection = person_property_projection(self.team.id, self.schema.id)
        return {source.key_column: sorted(source.columns) for source in (projection or [])}

    def test_returns_none_when_no_person_sources(self):
        assert person_property_projection(self.team.id, self.schema.id) is None

    def test_projects_key_and_mapped_columns_per_enabled_person_source(self):
        self._person_source("A", "distinct_id", {"plan": "plan_tier"})
        self._person_source("B", "user_id", {"seats": "seat_count", "region": "region"})

        assert self._projected() == {
            "distinct_id": ["distinct_id", "plan"],
            "user_id": ["region", "seats", "user_id"],
        }

    def test_skips_source_without_key_column(self):
        # A source with no key column has no person identifier to attach properties to.
        self._person_source("keyless", "", {"plan": "plan_tier"})

        assert person_property_projection(self.team.id, self.schema.id) is None

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

        assert self._projected() == {"distinct_id": ["distinct_id", "plan"]}

    def test_sync_sources_carry_full_config_for_the_upsert_job(self):
        # The warehouse-owned sync job consumes these configs through the hook; a wrong field
        # mapping here mis-stamps provenance or upserts the wrong columns.
        source = self._person_source("A", "distinct_id", {"plan": "plan_tier"})

        configs = person_property_sync_sources(self.team.id, self.schema.id)

        assert configs is not None and len(configs) == 1
        config = configs[0]
        assert config.source_id == str(source.id)
        assert config.definition_id == str(source.definition_id)
        assert config.key_column == "distinct_id"
        assert config.column_property_map == {"plan": "plan_tier"}

    def test_sync_sources_none_when_no_person_sources(self):
        assert person_property_sync_sources(self.team.id, self.schema.id) is None

    def test_flag_off_disables_both_resolvers_despite_configured_sources(self):
        # The resolvers are the pipeline choke point for the rollout flag: with the flag off,
        # configured sources must not stage rows or start the sync workflow.
        self._person_source("A", "distinct_id", {"plan": "plan_tier"})
        with patch(
            "products.customer_analytics.backend.logic.person_property_projection.person_properties_flag_enabled",
            return_value=False,
        ):
            assert person_property_projection(self.team.id, self.schema.id) is None
            assert person_property_sync_sources(self.team.id, self.schema.id) is None
