from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import GorgiasSourceConfig
from posthog.temporal.data_imports.sources.gorgias.gorgias import GorgiasResumeConfig
from posthog.temporal.data_imports.sources.gorgias.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.gorgias.source import GorgiasSource

from products.data_warehouse.backend.types import ExternalDataSourceType

SOURCE_MODULE = "posthog.temporal.data_imports.sources.gorgias.source"


def _config() -> GorgiasSourceConfig:
    return GorgiasSourceConfig(gorgias_domain="acme", email="you@acme.com", api_key="key")


def _inputs(schema_name: str = "tickets") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestGorgiasSource:
    def test_source_type(self) -> None:
        assert GorgiasSource().source_type == ExternalDataSourceType.GORGIAS

    def test_source_config_fields(self) -> None:
        config = GorgiasSource().get_source_config
        assert config.label == "Gorgias"
        assert config.releaseStatus == "alpha"

        fields = {f.name: f for f in config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"gorgias_domain", "email", "api_key"}
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].secret is True
        assert fields["email"].type == SourceFieldInputConfigType.EMAIL
        assert all(fields[name].required for name in fields)

    def test_get_schemas_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = GorgiasSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Gorgias has no server-side timestamp filter, so nothing supports incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = GorgiasSource().get_schemas(_config(), team_id=1, names=["tickets", "customers"])
        assert {s.name for s in schemas} == {"tickets", "customers"}

    @parameterized.expand(
        [
            ("valid", (True, None), True),
            ("invalid", (False, "Invalid Gorgias credentials. Check your domain, email, and API key."), False),
        ]
    )
    def test_validate_credentials_delegates(self, _name: str, transport_result: tuple, expected_valid: bool) -> None:
        with patch(f"{SOURCE_MODULE}.validate_gorgias_credentials", return_value=transport_result) as mocked:
            valid, _error = GorgiasSource().validate_credentials(_config(), team_id=1)
        assert valid is expected_valid
        mocked.assert_called_once_with("acme", "you@acme.com", "key")

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = GorgiasSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GorgiasResumeConfig

    def test_source_for_pipeline_plumbs_schema_name(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = GorgiasSource().source_for_pipeline(_config(), manager, _inputs(schema_name="customers"))
        assert response.name == "customers"
        assert response.primary_keys == ["id"]

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = GorgiasSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
