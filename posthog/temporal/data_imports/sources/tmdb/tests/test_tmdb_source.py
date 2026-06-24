import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import TMDbSourceConfig
from posthog.temporal.data_imports.sources.tmdb.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.tmdb.source import TMDbSource
from posthog.temporal.data_imports.sources.tmdb.tmdb import TMDbResumeConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestTMDbSource:
    def setup_method(self) -> None:
        self.source = TMDbSource()
        self.team_id = 123
        self.config = TMDbSourceConfig(api_key="tmdb-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TMDB

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "TMDb"
        assert config.label == "TMDb"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/tmdb.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # TMDB v3 exposes no server-side updated-after filter, so every schema is full refresh.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["movie_popular"])
        assert len(schemas) == 1
        assert schemas[0].name == "movie_popular"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.themoviedb.org/3/movie/popular?api_key=x&page=1",
            "401 Client Error: Unauthorized for url: https://api.themoviedb.org/3/configuration",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error for url: https://api.themoviedb.org/3/movie/popular",
            "404 Client Error: Not Found for url: https://api.themoviedb.org/3/movie/0",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "valid, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid TMDB API key"),
        ],
    )
    @mock.patch("posthog.temporal.data_imports.sources.tmdb.source.validate_tmdb_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        valid: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = valid
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with("tmdb-key")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TMDbResumeConfig

    def test_canonical_descriptions_keyed_by_known_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Only documents endpoints that actually exist; partial coverage is allowed.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "movie_popular" in descriptions

    @mock.patch("posthog.temporal.data_imports.sources.tmdb.source.tmdb_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_tmdb_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "movie_popular"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_tmdb_source.assert_called_once()
        kwargs = mock_tmdb_source.call_args.kwargs
        assert kwargs["api_key"] == "tmdb-key"
        assert kwargs["endpoint"] == "movie_popular"
        assert kwargs["resumable_source_manager"] is manager
