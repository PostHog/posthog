import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import NotionSourceConfig
from posthog.temporal.data_imports.sources.notion.notion import NotionResumeConfig
from posthog.temporal.data_imports.sources.notion.settings import data_source_rows_schema_name
from posthog.temporal.data_imports.sources.notion.source import NotionSource


class TestNotionSource:
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

    @patch("posthog.temporal.data_imports.sources.notion.source.notion_source")
    @patch.object(NotionSource, "_get_access_token")
    def test_source_for_pipeline_passes_inputs_through(
        self, mock_get_token: MagicMock, mock_notion_source: MagicMock
    ) -> None:
        # Anchor the wiring between SourceInputs and notion_source — team_id, job_id, the
        # incremental cursor field, and the schema name all need to make it through.
        # A regression here would silently break incremental sync without test coverage.
        mock_get_token.return_value = "tok"
        sentinel = object()
        mock_notion_source.return_value = sentinel

        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock(
            schema_name="data_source_rows__abc",
            team_id=42,
            job_id="job-xyz",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-05-01T00:00:00Z",
            incremental_field="last_edited_time",
        )

        response = NotionSource().source_for_pipeline(
            config=NotionSourceConfig(notion_integration_id=1),
            resumable_source_manager=manager,
            inputs=inputs,
        )

        assert response is sentinel
        kwargs = mock_notion_source.call_args.kwargs
        assert kwargs["access_token"] == "tok"
        assert kwargs["endpoint_name"] == "data_source_rows__abc"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-05-01T00:00:00Z"
        assert kwargs["incremental_field"] == "last_edited_time"

    @patch.object(NotionSource, "_get_access_token")
    def test_source_for_pipeline_omits_incremental_state_for_full_refresh(self, mock_get_token: MagicMock) -> None:
        # When the schema is configured for full refresh, neither the cursor value nor the
        # selected field should leak through — otherwise the pipeline would erroneously
        # resume from a stale point.
        mock_get_token.return_value = "tok"
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = MagicMock(
            schema_name="users",
            team_id=1,
            job_id="j",
            should_use_incremental_field=False,
            db_incremental_field_last_value="leftover-cursor",
            incremental_field="last_edited_time",
        )

        with patch("posthog.temporal.data_imports.sources.notion.source.notion_source") as mock_notion_source:
            NotionSource().source_for_pipeline(
                config=NotionSourceConfig(notion_integration_id=1),
                resumable_source_manager=manager,
                inputs=inputs,
            )

        kwargs = mock_notion_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["incremental_field"] is None

    def test_get_resumable_source_manager_returns_manager_bound_to_resume_config(self) -> None:
        # ResumableSourceManager is generic over the resume dataclass and uses it to
        # serialize/deserialize Redis state. Wiring the wrong class would silently corrupt
        # checkpoints across crashes.
        inputs = MagicMock(team_id=1, job_id="j", logger=MagicMock())
        manager = NotionSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        # `_data_class` is the source-of-truth field the manager uses to round-trip state.
        assert manager._data_class is NotionResumeConfig
