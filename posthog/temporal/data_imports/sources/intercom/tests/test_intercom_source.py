from unittest import mock

from posthog.temporal.data_imports.sources.intercom.source import IntercomSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestIntercomSource:
    def setup_method(self):
        self.source = IntercomSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.INTERCOM

    def test_get_source_config_has_api_key_field(self):
        config = self.source.get_source_config
        assert config.betaSource is True
        assert len(config.fields) == 1
        assert config.fields[0].name == "api_key"

    def test_get_schemas_returns_all_endpoints(self):
        mock_config = mock.MagicMock()
        schemas = self.source.get_schemas(mock_config, team_id=1)
        assert len(schemas) == 7
        schema_names = {s.name for s in schemas}
        assert schema_names == {"contacts", "conversations", "companies", "admins", "tags", "teams", "data_attributes"}

    def test_contacts_and_conversations_support_incremental(self):
        mock_config = mock.MagicMock()
        schemas = self.source.get_schemas(mock_config, team_id=1)
        schemas_by_name = {s.name: s for s in schemas}

        assert schemas_by_name["contacts"].supports_incremental is True
        assert schemas_by_name["conversations"].supports_incremental is True
        assert schemas_by_name["companies"].supports_incremental is False
        assert schemas_by_name["admins"].supports_incremental is False

    def test_get_schemas_filters_by_names(self):
        mock_config = mock.MagicMock()
        schemas = self.source.get_schemas(mock_config, team_id=1, names=["contacts", "admins"])
        assert len(schemas) == 2
        assert {s.name for s in schemas} == {"contacts", "admins"}

    @mock.patch("posthog.temporal.data_imports.sources.intercom.source.validate_intercom_credentials")
    def test_validate_credentials_delegates(self, mock_validate):
        mock_validate.return_value = (True, None)
        mock_config = mock.MagicMock()
        mock_config.api_key = "test_key"

        result = self.source.validate_credentials(mock_config, team_id=1)

        assert result == (True, None)
        mock_validate.assert_called_once_with("test_key")

    def test_get_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error: Unauthorized for url: https://api.intercom.io" in errors
        assert "403 Client Error: Forbidden for url: https://api.intercom.io" in errors
