from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized, parameterized_class

from products.customer_analytics.backend.logic.person_property_projection import (
    person_property_projection,
    person_property_sync_sources,
)
from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_custom_property_definition, create_saved_query
from products.warehouse_sources.backend.facade.hooks import saved_query_binding, schema_binding
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


# Both binding kinds run every case: the resolvers pick the filter column from the binding, and picking
# the wrong one leaves a configured source silently never syncing.
@parameterized_class(("binding_kind",), [("schema",), ("saved_query",)])
class PersonPropertyProjectionTest(TeamScopedTestMixin, BaseTest):
    binding_kind = "schema"

    def setUp(self):
        super().setUp()
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Stripe"
        )
        self.schema = ExternalDataSchema.objects.create(team=self.team, source=source, name="users")
        self.saved_query = create_saved_query(team_id=self.team.id)
        flag_patch = patch(
            "products.customer_analytics.backend.logic.person_property_projection.person_properties_flag_enabled",
            return_value=True,
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

    @property
    def binding(self):
        if self.binding_kind == "saved_query":
            return saved_query_binding(self.saved_query.id)
        return schema_binding(self.schema.id)

    def _binding_kwargs(self):
        if self.binding_kind == "saved_query":
            return {"saved_query": self.saved_query}
        return {"external_data_schema": self.schema}

    def _person_source(self, name, key_column, column_property_map, *, is_enabled=True, column_descriptions=None):
        definition = create_custom_property_definition(
            team_id=self.team.id, name=name, target_type=TargetType.PERSON.value
        )
        return CustomPropertySource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            definition=definition,
            key_column=key_column,
            column_property_map=column_property_map,
            column_descriptions=column_descriptions,
            is_enabled=is_enabled,
            **self._binding_kwargs(),
        )

    def _projected(self):
        projection = person_property_projection(self.team.id, self.binding)
        return {source.key_column: sorted(source.columns) for source in (projection or [])}

    def test_returns_none_when_no_person_sources(self):
        assert person_property_projection(self.team.id, self.binding) is None

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

        assert person_property_projection(self.team.id, self.binding) is None

    def test_ignores_disabled_account_and_other_binding_sources(self):
        self._person_source("enabled", "distinct_id", {"plan": "plan_tier"})
        self._person_source("disabled", "other_id", {"col": "prop"}, is_enabled=False)

        # Account-target source on the same warehouse object must not contribute.
        account_def = create_custom_property_definition(
            team_id=self.team.id, name="MRR", target_type=TargetType.ACCOUNT.value
        )
        CustomPropertySource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            definition=account_def,
            key_column="acct_id",
            column_property_map={"mrr": "mrr"},
            **self._binding_kwargs(),
        )

        assert self._projected() == {"distinct_id": ["distinct_id", "plan"]}

    def test_ignores_a_source_bound_to_the_other_warehouse_object(self):
        # The two binding kinds must not bleed into each other: a source on the view must not surface
        # for the schema's run, or its properties would update off the wrong table's rows.
        self._person_source("A", "distinct_id", {"plan": "plan_tier"})
        other = (
            schema_binding(self.schema.id)
            if self.binding_kind == "saved_query"
            else saved_query_binding(self.saved_query.id)
        )

        assert person_property_projection(self.team.id, other) is None
        assert person_property_sync_sources(self.team.id, other) is None

    def test_sync_sources_carry_full_config_for_the_upsert_job(self):
        # The warehouse-owned sync job consumes these configs through the hook; a wrong field
        # mapping here mis-stamps provenance or upserts the wrong columns.
        source = self._person_source("A", "distinct_id", {"plan": "plan_tier"})

        configs = person_property_sync_sources(self.team.id, self.binding)

        assert configs is not None and len(configs) == 1
        config = configs[0]
        assert config.source_id == str(source.id)
        assert config.definition_id == str(source.definition_id)
        assert config.key_column == "distinct_id"
        assert config.column_property_map == {"plan": "plan_tier"}
        # No descriptions configured -> empty mapping, not None.
        assert config.property_descriptions == {}

    def test_sync_sources_rekey_column_descriptions_onto_property_names(self):
        # Descriptions are stored keyed by warehouse column but stamped onto property definitions
        # keyed by property name; the resolver must re-key and drop descriptions for unmapped columns.
        self._person_source(
            "A",
            "distinct_id",
            {"plan": "plan_tier", "seats": "seat_count"},
            column_descriptions={"plan": "The plan tier", "unmapped": "ignored", "seats": ""},
        )

        configs = person_property_sync_sources(self.team.id, self.binding)

        assert configs is not None and len(configs) == 1
        # 'plan' re-keyed to 'plan_tier'; 'unmapped' dropped (no column); 'seats' dropped (blank).
        assert configs[0].property_descriptions == {"plan_tier": "The plan tier"}

    def test_sync_sources_none_when_no_person_sources(self):
        assert person_property_sync_sources(self.team.id, self.binding) is None

    @parameterized.expand([("projection", person_property_projection), ("sync_sources", person_property_sync_sources)])
    def test_flag_off_disables_the_resolver_despite_configured_sources(self, _name, resolver):
        # The resolvers are the pipeline choke point for the rollout flag: with the flag off,
        # configured sources must not stage rows or start the sync workflow.
        self._person_source("A", "distinct_id", {"plan": "plan_tier"})
        with patch(
            "products.customer_analytics.backend.logic.person_property_projection.person_properties_flag_enabled",
            return_value=False,
        ):
            assert resolver(self.team.id, self.binding) is None
