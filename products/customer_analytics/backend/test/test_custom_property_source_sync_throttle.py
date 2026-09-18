from posthog.test.base import APIBaseTest

from posthog.rate_limit import RunSavedQueryRateThrottle

from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.customer_analytics.backend.presentation.views.views import CustomPropertySourceSyncThrottle
from products.customer_analytics.backend.test.factories import create_custom_property_definition, create_saved_query
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


class _FakeView:
    def __init__(self, team_id: int, pk: str) -> None:
        self.team_id = team_id
        self.kwargs = {"pk": pk}


class TestCustomPropertySourceSyncThrottle(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.saved_query = create_saved_query(team_id=self.team.id)

    def _source(self, name: str, **binding) -> CustomPropertySource:
        definition = create_custom_property_definition(
            team_id=self.team.id, name=name, target_type=TargetType.PERSON.value
        )
        return CustomPropertySource.objects.unscoped().create(
            team_id=self.team.id, definition=definition, key_column="distinct_id", **binding
        )

    def _sync_key(self, source: CustomPropertySource) -> str | None:
        return CustomPropertySourceSyncThrottle().get_cache_key(None, _FakeView(self.team.id, str(source.id)))

    def test_view_backed_sync_shares_the_canonical_saved_query_bucket(self):
        first = self._source("Plan tier", saved_query_id=self.saved_query.id)
        second = self._source("Seat count", saved_query_id=self.saved_query.id)
        canonical = RunSavedQueryRateThrottle().get_cache_key(None, _FakeView(self.team.id, str(self.saved_query.id)))

        # Syncing either mapping counts against the view's own run limit, so a caller can't get extra
        # materializations by routing through this endpoint or by adding a second mapping on the view.
        assert self._sync_key(first) == canonical
        assert self._sync_key(second) == canonical

    def test_table_backed_sync_keys_on_the_schema(self):
        external_source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(team=self.team, source=external_source, name="users")
        source = self._source("Plan tier", external_data_schema_id=schema.id)

        assert str(schema.id) in (self._sync_key(source) or "")
        assert str(source.id) not in (self._sync_key(source) or "")
