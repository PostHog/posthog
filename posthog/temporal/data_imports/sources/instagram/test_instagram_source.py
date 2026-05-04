from unittest import mock

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import InstagramSourceConfig
from posthog.temporal.data_imports.sources.instagram.instagram import InstagramResumeConfig
from posthog.temporal.data_imports.sources.instagram.schemas import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.instagram.source import InstagramSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestInstagramSource:
    def setup_method(self):
        self.source = InstagramSource()
        self.team_id = 123
        self.config = InstagramSourceConfig(
            ig_user_id="17841400000000000",
            instagram_integration_id=456,
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.INSTAGRAM

    def test_get_source_config_basics(self):
        config = self.source.get_source_config
        assert config.label == "Instagram"
        assert config.iconPath == "/static/services/instagram.png"
        assert config.releaseStatus == "alpha"
        assert config.featureFlag == "dwh-instagram"
        # Three fields: ig_user_id, instagram_integration_id (OAuth), sync_lookback_days.
        names = [getattr(f, "name", None) for f in config.fields]
        assert "ig_user_id" in names
        assert "instagram_integration_id" in names
        assert "sync_lookback_days" in names

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == {e.value for e in ENDPOINTS}

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users", "media"])
        assert {s.name for s in schemas} == {"users", "media"}

    def test_only_user_insights_supports_incremental(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        incremental_names = {s.name for s in schemas if s.supports_incremental}
        assert incremental_names == set(INCREMENTAL_FIELDS.keys())
        assert incremental_names == {"user_insights"}

    def test_validate_credentials_missing_ig_user_id(self):
        invalid_config = InstagramSourceConfig(ig_user_id="", instagram_integration_id=456)
        ok, error = self.source.validate_credentials(invalid_config, self.team_id)
        assert ok is False
        assert error is not None
        assert "Instagram" in error

    @mock.patch("posthog.temporal.data_imports.sources.instagram.source.Integration")
    def test_validate_credentials_integration_missing(self, mock_integration):
        class MockDoesNotExist(Exception):
            pass

        mock_integration.DoesNotExist = MockDoesNotExist
        mock_integration.objects.get.side_effect = MockDoesNotExist()

        ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error is not None
        assert "Instagram integration not found" in error

    @mock.patch("posthog.temporal.data_imports.sources.instagram.source.Integration")
    def test_validate_credentials_success(self, mock_integration):
        mock_integration.DoesNotExist = type("MockDoesNotExist", (Exception,), {})
        mock_integration.objects.get.return_value = mock.MagicMock()
        ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is True
        assert error is None

    def test_get_resumable_source_manager_returns_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        # The manager is parameterized over InstagramResumeConfig — saving/loading state
        # should round-trip through that dataclass. Smoke-check the binding via the
        # private attribute set at construction time.
        assert manager._data_class is InstagramResumeConfig

    @mock.patch("posthog.temporal.data_imports.sources.instagram.source.instagram_source")
    def test_source_for_pipeline_passes_through(self, mock_source_fn):
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = mock.MagicMock()
        inputs.schema_name = "media"
        inputs.team_id = 7
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        inputs.incremental_field_type = None
        inputs.db_incremental_field_last_value = None

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source_fn.assert_called_once()
        call_kwargs = mock_source_fn.call_args.kwargs
        assert call_kwargs["resource_name"] == "media"
        assert call_kwargs["team_id"] == 7
        assert call_kwargs["resumable_source_manager"] is manager
        assert call_kwargs["should_use_incremental_field"] is False

    def test_get_non_retryable_errors_includes_token_failure(self):
        errors = self.source.get_non_retryable_errors()
        assert any("re-authorize" in key for key in errors)
        assert any("Error validating access token" in key for key in errors)
