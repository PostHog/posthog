from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.hubspot.settings import DEFAULT_PROPS, HUBSPOT_ENDPOINTS
from posthog.temporal.data_imports.sources.hubspot.source import HubspotSource

from products.data_warehouse.backend.types import IncrementalFieldType


def _make_inputs(
    schema_name: str = "deals",
    should_use_incremental_field: bool = True,
    db_incremental_field_last_value: str | None = "2026-01-01T00:00:00.000Z",
    reset_pipeline: bool = False,
    schema_id: str = "schema-1",
    team_id: int = 1,
    source_id: str = "source-1",
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id=schema_id,
        source_id=source_id,
        team_id=team_id,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=HUBSPOT_ENDPOINTS[schema_name].cursor_filter_property_field,
        incremental_field_type=IncrementalFieldType.DateTime,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=reset_pipeline,
    )


class TestGetSchemas:
    def test_declares_incremental_for_all_endpoints(self) -> None:
        src = HubspotSource()
        schemas = src.get_schemas(MagicMock(), team_id=1)

        by_name = {s.name: s for s in schemas}
        # All seven endpoints currently have cursor properties, so all should support incremental.
        assert set(by_name.keys()) == set(HUBSPOT_ENDPOINTS.keys())
        for name, schema in by_name.items():
            endpoint_config = HUBSPOT_ENDPOINTS[name]
            assert schema.supports_incremental is bool(endpoint_config.cursor_filter_property_field)
            assert schema.supports_append is schema.supports_incremental
            # Incremental field matches the cursor property
            expected_field = endpoint_config.cursor_filter_property_field
            if expected_field:
                assert schema.incremental_fields
                assert schema.incremental_fields[0]["field"] == expected_field

    def test_filters_by_names(self) -> None:
        src = HubspotSource()
        schemas = src.get_schemas(MagicMock(), team_id=1, names=["deals", "contacts"])
        assert {s.name for s in schemas} == {"deals", "contacts"}


class TestShouldUseSearchPath:
    def _patch_schema(self, initial_sync_complete: bool) -> Any:
        schema = MagicMock()
        schema.initial_sync_complete = initial_sync_complete
        return patch(
            "products.data_warehouse.backend.models.ExternalDataSchema.objects.get",
            return_value=schema,
        )

    def test_false_when_not_incremental(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs(should_use_incremental_field=False)
        # No DB query should be needed; not-incremental short-circuits first.
        assert src._should_use_search_path(inputs) is False

    def test_false_when_reset_pipeline(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs(reset_pipeline=True)
        assert src._should_use_search_path(inputs) is False

    def test_false_when_endpoint_has_no_cursor(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs(schema_name="deals")
        original = HUBSPOT_ENDPOINTS["deals"].cursor_filter_property_field
        HUBSPOT_ENDPOINTS["deals"].cursor_filter_property_field = None
        try:
            assert src._should_use_search_path(inputs) is False
        finally:
            HUBSPOT_ENDPOINTS["deals"].cursor_filter_property_field = original

    def test_false_when_initial_sync_not_complete(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs()
        with self._patch_schema(initial_sync_complete=False):
            assert src._should_use_search_path(inputs) is False

    def test_true_when_all_conditions_met(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs()
        with self._patch_schema(initial_sync_complete=True):
            assert src._should_use_search_path(inputs) is True

    def test_false_when_db_lookup_fails(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs()
        with patch(
            "products.data_warehouse.backend.models.ExternalDataSchema.objects.get",
            side_effect=Exception("db down"),
        ):
            assert src._should_use_search_path(inputs) is False


class TestSourceForPipelineRouting:
    """Verify that source_for_pipeline routes to the right get_rows/get_rows_via_search path."""

    def test_routes_to_search_when_eligible(self) -> None:
        src = HubspotSource()
        from posthog.temporal.data_imports.sources.hubspot.source import HubspotSourceOldConfig

        old_config = HubspotSourceOldConfig.from_dict(
            {"hubspot_secret_key": "secret", "hubspot_refresh_token": "refresh"}
        )
        inputs = _make_inputs()
        schema = MagicMock()
        schema.initial_sync_complete = True

        with (
            patch(
                "posthog.temporal.data_imports.sources.hubspot.source.hubspot_source",
                return_value=MagicMock(),
            ) as hubspot_source_mock,
            patch(
                "posthog.temporal.data_imports.sources.hubspot.source.hubspot_access_token_is_valid",
                return_value=True,
            ),
            patch(
                "products.data_warehouse.backend.models.ExternalDataSchema.objects.get",
                return_value=schema,
            ),
        ):
            src.source_for_pipeline(old_config, MagicMock(), inputs)

        hubspot_source_mock.assert_called_once()
        assert hubspot_source_mock.call_args.kwargs["use_search_path"] is True

    def test_routes_to_get_when_initial_sync_not_complete(self) -> None:
        src = HubspotSource()
        from posthog.temporal.data_imports.sources.hubspot.source import HubspotSourceOldConfig

        old_config = HubspotSourceOldConfig.from_dict(
            {"hubspot_secret_key": "secret", "hubspot_refresh_token": "refresh"}
        )
        inputs = _make_inputs()
        schema = MagicMock()
        schema.initial_sync_complete = False

        with (
            patch(
                "posthog.temporal.data_imports.sources.hubspot.source.hubspot_source",
                return_value=MagicMock(),
            ) as hubspot_source_mock,
            patch(
                "posthog.temporal.data_imports.sources.hubspot.source.hubspot_access_token_is_valid",
                return_value=True,
            ),
            patch(
                "products.data_warehouse.backend.models.ExternalDataSchema.objects.get",
                return_value=schema,
            ),
        ):
            src.source_for_pipeline(old_config, MagicMock(), inputs)

        assert hubspot_source_mock.call_args.kwargs["use_search_path"] is False

    def test_routes_to_get_for_full_refresh(self) -> None:
        src = HubspotSource()
        from posthog.temporal.data_imports.sources.hubspot.source import HubspotSourceOldConfig

        old_config = HubspotSourceOldConfig.from_dict(
            {"hubspot_secret_key": "secret", "hubspot_refresh_token": "refresh"}
        )
        inputs = _make_inputs(should_use_incremental_field=False)

        with (
            patch(
                "posthog.temporal.data_imports.sources.hubspot.source.hubspot_source",
                return_value=MagicMock(),
            ) as hubspot_source_mock,
            patch(
                "posthog.temporal.data_imports.sources.hubspot.source.hubspot_access_token_is_valid",
                return_value=True,
            ),
        ):
            src.source_for_pipeline(old_config, MagicMock(), inputs)

        assert hubspot_source_mock.call_args.kwargs["use_search_path"] is False


class TestSettingsShape:
    @pytest.mark.parametrize("endpoint", list(HUBSPOT_ENDPOINTS.keys()))
    def test_cursor_property_is_in_default_props(self, endpoint: str) -> None:
        config = HUBSPOT_ENDPOINTS[endpoint]
        assert config.cursor_filter_property_field is not None
        # The cursor property must be in the request so the flattened row carries it
        assert config.cursor_filter_property_field in DEFAULT_PROPS[endpoint]

    @pytest.mark.parametrize("endpoint", list(HUBSPOT_ENDPOINTS.keys()))
    def test_hs_object_id_is_in_default_props(self, endpoint: str) -> None:
        # Required so we can extract the primary key for association lookups
        assert "hs_object_id" in DEFAULT_PROPS[endpoint]

    @pytest.mark.parametrize("endpoint", list(HUBSPOT_ENDPOINTS.keys()))
    def test_incremental_field_matches_cursor_property(self, endpoint: str) -> None:
        config = HUBSPOT_ENDPOINTS[endpoint]
        assert config.incremental_fields
        field = config.incremental_fields[0]
        assert field["field"] == config.cursor_filter_property_field
        assert field["type"] == IncrementalFieldType.DateTime
