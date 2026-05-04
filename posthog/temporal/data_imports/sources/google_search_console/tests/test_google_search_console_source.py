import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.generated_configs import GoogleSearchConsoleSourceConfig
from posthog.temporal.data_imports.sources.google_search_console.google_search_console import (
    GoogleSearchConsoleResumeConfig,
)
from posthog.temporal.data_imports.sources.google_search_console.settings import SEARCH_ANALYTICS_SCHEMAS
from posthog.temporal.data_imports.sources.google_search_console.source import GoogleSearchConsoleSource

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalFieldType


def _config() -> GoogleSearchConsoleSourceConfig:
    return GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )


def test_source_type():
    assert GoogleSearchConsoleSource().source_type == ExternalDataSourceType.GOOGLESEARCHCONSOLE


def test_get_source_config_fields():
    cfg = GoogleSearchConsoleSource().get_source_config

    field_names = {field.name for field in cfg.fields}
    assert field_names == {"google_search_console_integration_id", "site_url"}
    assert cfg.label == "Google Search Console"
    assert cfg.featureFlag == "dwh-google-search-console"
    assert cfg.releaseStatus == "alpha"
    assert cfg.unreleasedSource is True


def test_get_schemas_returns_all_schemas_with_date_incremental():
    schemas = GoogleSearchConsoleSource().get_schemas(_config(), team_id=1)

    assert {s.name for s in schemas} == set(SEARCH_ANALYTICS_SCHEMAS.keys())
    for schema in schemas:
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert schema.incremental_fields == [
            {
                "label": "date",
                "field": "date",
                "type": IncrementalFieldType.Date,
                "field_type": IncrementalFieldType.Date,
            }
        ]


def test_get_schemas_only_query_page_default():
    schemas = GoogleSearchConsoleSource().get_schemas(_config(), team_id=1)
    by_default_on = {s.name for s in schemas if s.should_sync_default}
    assert by_default_on == {"search_analytics_by_query_page"}


def test_get_schemas_filters_by_names():
    schemas = GoogleSearchConsoleSource().get_schemas(
        _config(), team_id=1, names=["search_analytics_by_date", "search_analytics_by_query"]
    )
    assert {s.name for s in schemas} == {"search_analytics_by_date", "search_analytics_by_query"}


def test_get_resumable_source_manager_uses_resume_config():
    inputs = mock.MagicMock()
    manager = GoogleSearchConsoleSource().get_resumable_source_manager(inputs)
    assert manager._data_class is GoogleSearchConsoleResumeConfig


@pytest.mark.parametrize(
    "status_code,expected_substring",
    [
        (401, "rejected the credentials"),
        (403, "rejected the credentials"),
    ],
)
def test_validate_credentials_handles_auth_failures(status_code, expected_substring):
    import requests

    with mock.patch(
        "posthog.temporal.data_imports.sources.google_search_console.source.google_search_console_session"
    ) as mock_session_factory:
        response = mock.MagicMock()
        response.status_code = status_code
        err = requests.HTTPError(response=response)
        session = mock.MagicMock()
        session.get.return_value.raise_for_status.side_effect = err
        mock_session_factory.return_value = session

        with mock.patch(
            "posthog.temporal.data_imports.sources.google_search_console.source.list_sites",
            side_effect=err,
        ):
            ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert expected_substring in (message or "")


def test_validate_credentials_rejects_unknown_site():
    with (
        mock.patch("posthog.temporal.data_imports.sources.google_search_console.source.google_search_console_session"),
        mock.patch(
            "posthog.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[
                {"siteUrl": "https://other.example.com/", "permissionLevel": "siteOwner"},
            ],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "is not visible to the connected Google account" in (message or "")


def test_validate_credentials_rejects_unverified_user():
    with (
        mock.patch("posthog.temporal.data_imports.sources.google_search_console.source.google_search_console_session"),
        mock.patch(
            "posthog.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[
                {"siteUrl": "https://example.com/", "permissionLevel": "siteUnverifiedUser"},
            ],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "verified access" in (message or "")


def test_validate_credentials_succeeds_for_verified_site():
    with (
        mock.patch("posthog.temporal.data_imports.sources.google_search_console.source.google_search_console_session"),
        mock.patch(
            "posthog.temporal.data_imports.sources.google_search_console.source.list_sites",
            return_value=[
                {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
            ],
        ),
    ):
        ok, message = GoogleSearchConsoleSource().validate_credentials(_config(), team_id=1)

    assert ok is True
    assert message is None
