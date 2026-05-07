import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
)

from posthog.temporal.data_imports.sources.posthog_mwh.source import PostHogMWHSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestPostHogMWHSource:
    def setup_method(self):
        self.source = PostHogMWHSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.POSTHOGMWH

    def test_source_config_name(self):
        config = self.source.get_source_config
        assert config.name == SchemaExternalDataSourceType.POST_HOG_MWH

    def test_source_config_feature_flag(self):
        config = self.source.get_source_config
        assert config.featureFlag == "provision-managed-warehouse-beta"

    def test_source_config_empty_fields(self):
        config = self.source.get_source_config
        assert config.fields == []

    def test_source_config_beta_release_status(self):
        config = self.source.get_source_config
        assert config.releaseStatus == ReleaseStatus.BETA

    def test_source_for_pipeline_raises(self):
        with pytest.raises(NotImplementedError, match="COPY TO S3"):
            self.source.source_for_pipeline(MagicMock(), MagicMock())

    @patch("posthog.temporal.data_imports.sources.posthog_mwh.source.make_duckgres_conninfo")
    @patch("posthog.temporal.data_imports.sources.posthog_mwh.source.psycopg")
    def test_validate_credentials_success(self, mock_psycopg, mock_conninfo):
        mock_conninfo.return_value = "host=localhost dbname=test"
        mock_conn = MagicMock()
        mock_psycopg.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = MagicMock(return_value=False)

        ok, err = self.source.validate_credentials(MagicMock(), team_id=1)
        assert ok is True
        assert err is None

    @patch("posthog.temporal.data_imports.sources.posthog_mwh.source.make_duckgres_conninfo")
    def test_validate_credentials_connection_failure(self, mock_conninfo):
        mock_conninfo.side_effect = Exception("no duckgres server")

        ok, err = self.source.validate_credentials(MagicMock(), team_id=1)
        assert ok is False
        assert "no duckgres server" in err

    @patch("posthog.temporal.data_imports.sources.posthog_mwh.source.get_mwh_tables")
    @patch("posthog.temporal.data_imports.sources.posthog_mwh.source.get_mwh_columns")
    def test_get_schemas_returns_tables(self, mock_columns, mock_tables):
        mock_tables.return_value = [
            {"schema": "revenue", "table": "orders"},
            {"schema": "stripe", "table": "payments"},
        ]
        mock_columns.return_value = [
            ("id", "integer", False),
            ("amount", "numeric", True),
        ]

        schemas = self.source.get_schemas(MagicMock(), team_id=1)

        assert len(schemas) == 2
        assert schemas[0].name == "revenue.orders"
        assert schemas[0].supports_incremental is False
        assert schemas[0].supports_append is False
        assert schemas[0].source_schema == "revenue"
        assert schemas[0].source_table_name == "orders"
        assert schemas[1].name == "stripe.payments"

    @patch("posthog.temporal.data_imports.sources.posthog_mwh.source.get_mwh_tables")
    @patch("posthog.temporal.data_imports.sources.posthog_mwh.source.get_mwh_columns")
    def test_get_schemas_filters_by_names(self, mock_columns, mock_tables):
        mock_tables.return_value = [
            {"schema": "revenue", "table": "orders"},
            {"schema": "stripe", "table": "payments"},
        ]
        mock_columns.return_value = [("id", "integer", False)]

        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["revenue.orders"])

        assert len(schemas) == 1
        assert schemas[0].name == "revenue.orders"
