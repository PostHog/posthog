import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldOauthConfig

from posthog.temporal.data_imports.sources.generated_configs import NotionSourceConfig
from posthog.temporal.data_imports.sources.notion.settings import data_source_rows_schema_name
from posthog.temporal.data_imports.sources.notion.source import NotionSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestNotionSource:
    def test_source_type(self) -> None:
        assert NotionSource().source_type == ExternalDataSourceType.NOTION

    def test_source_config_exposes_oauth_field(self) -> None:
        config = NotionSource().get_source_config
        assert config.label == "Notion"
        assert config.releaseStatus == "alpha"
        assert config.featureFlag == "dwh-notion"
        assert config.iconPath == "/static/services/notion.png"

        oauth_fields = [f for f in config.fields if isinstance(f, SourceFieldOauthConfig) and f.kind == "notion"]
        assert len(oauth_fields) == 1
        assert oauth_fields[0].name == "notion_integration_id"
        assert oauth_fields[0].required is True

    def test_non_retryable_errors_cover_auth(self) -> None:
        errors = NotionSource().get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors

    @patch("posthog.temporal.data_imports.sources.notion.source._list_data_sources")
    @patch.object(NotionSource, "_get_access_token")
    def test_get_schemas_returns_static_plus_data_sources(
        self, mock_get_token: MagicMock, mock_list_data_sources: MagicMock
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_list_data_sources.return_value = [("ds-id-aaa", "Engineering tasks"), ("ds-id-bbb", None)]

        schemas = NotionSource().get_schemas(config=NotionSourceConfig(notion_integration_id=1), team_id=1)
        by_name = {s.name: s for s in schemas}

        assert "users" in by_name
        assert "pages" in by_name
        assert "data_sources" in by_name
        assert data_source_rows_schema_name("ds-id-aaa") in by_name
        assert data_source_rows_schema_name("ds-id-bbb") in by_name

        # Static endpoints with incremental support are flagged correctly.
        assert by_name["pages"].supports_incremental is True
        assert by_name["pages"].supports_append is True
        assert by_name["users"].supports_incremental is False

        # Data source row schemas use the Notion data source title as their label,
        # falling back to "Untitled data source" when the title is empty.
        assert by_name[data_source_rows_schema_name("ds-id-aaa")].label == "Engineering tasks"
        assert by_name[data_source_rows_schema_name("ds-id-bbb")].label == "Untitled data source"

    @patch("posthog.temporal.data_imports.sources.notion.source._list_data_sources")
    @patch.object(NotionSource, "_get_access_token")
    def test_get_schemas_raises_when_data_source_discovery_fails(
        self, mock_get_token: MagicMock, mock_list_data_sources: MagicMock
    ) -> None:
        # Surface real errors (revoked token, missing scope, Notion outage) rather than
        # silently degrading to only the static schemas — which would mask broken syncs.
        mock_get_token.return_value = "tok"
        mock_list_data_sources.side_effect = Exception("notion api down")

        with pytest.raises(Exception, match="notion api down"):
            NotionSource().get_schemas(config=NotionSourceConfig(notion_integration_id=1), team_id=1)

    @patch("posthog.temporal.data_imports.sources.notion.source._list_data_sources")
    @patch.object(NotionSource, "_get_access_token")
    def test_get_schemas_skips_data_source_discovery_for_static_only_names(
        self, mock_get_token: MagicMock, mock_list_data_sources: MagicMock
    ) -> None:
        # When the caller (e.g. the `incremental_fields` API endpoint) only asks about
        # static schemas, we shouldn't hit the Notion API at all.
        mock_get_token.return_value = "tok"

        schemas = NotionSource().get_schemas(
            config=NotionSourceConfig(notion_integration_id=1),
            team_id=1,
            names=["pages"],
        )

        assert [s.name for s in schemas] == ["pages"]
        mock_list_data_sources.assert_not_called()
        mock_get_token.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.notion.source._list_data_sources")
    @patch.object(NotionSource, "_get_access_token")
    def test_get_schemas_uses_per_id_fetch_when_dynamic_name_requested(
        self, mock_get_token: MagicMock, mock_list_data_sources: MagicMock
    ) -> None:
        # When the caller asks about a specific `data_source_rows__*` schema, we should
        # fetch that data source by id (one targeted GET) rather than paginating the whole
        # workspace via /v1/search.
        mock_get_token.return_value = "tok"
        mock_list_data_sources.return_value = [("ds-id-aaa", "Engineering tasks")]

        target = data_source_rows_schema_name("ds-id-aaa")
        schemas = NotionSource().get_schemas(
            config=NotionSourceConfig(notion_integration_id=1),
            team_id=1,
            names=[target],
        )

        assert [s.name for s in schemas] == [target]
        # The hyphenless id encoded in the schema name is what gets passed down — Notion
        # accepts both hyphenated and hyphenless UUIDs at /v1/data_sources/{id}.
        mock_list_data_sources.assert_called_once_with("tok", ids=["dsidaaa"])

    @patch("posthog.temporal.data_imports.sources.notion.source._list_data_sources")
    @patch.object(NotionSource, "_get_access_token")
    def test_get_schemas_does_full_enumeration_when_names_is_none(
        self, mock_get_token: MagicMock, mock_list_data_sources: MagicMock
    ) -> None:
        # Without a `names` filter we still want the full /v1/search enumeration — that
        # path is cheaper than per-id when we don't yet know what data sources exist.
        mock_get_token.return_value = "tok"
        mock_list_data_sources.return_value = []

        NotionSource().get_schemas(config=NotionSourceConfig(notion_integration_id=1), team_id=1)

        mock_list_data_sources.assert_called_once_with("tok", ids=None)

    @patch("posthog.temporal.data_imports.sources.notion.source.validate_notion_credentials")
    @patch.object(NotionSource, "_get_access_token")
    def test_validate_credentials_delegates_to_notion_module(
        self, mock_get_token: MagicMock, mock_validate: MagicMock
    ) -> None:
        mock_get_token.return_value = "tok"
        mock_validate.return_value = (True, None)

        ok, err = NotionSource().validate_credentials(config=NotionSourceConfig(notion_integration_id=1), team_id=1)
        assert ok is True
        assert err is None
        mock_validate.assert_called_once_with("tok")

    @patch.object(NotionSource, "_get_access_token")
    def test_validate_credentials_surfaces_token_errors(self, mock_get_token: MagicMock) -> None:
        mock_get_token.side_effect = ValueError("Notion access token not found")

        ok, err = NotionSource().validate_credentials(config=NotionSourceConfig(notion_integration_id=1), team_id=1)
        assert ok is False
        assert err is not None
        assert "Notion access token not found" in err
