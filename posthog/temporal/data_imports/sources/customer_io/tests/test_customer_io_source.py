from collections.abc import Iterable
from typing import Literal, cast

from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldSelectConfig

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from posthog.temporal.data_imports.sources.customer_io.constants import (
    CIO_API_SCHEMA_NAMES,
    CIO_WEBHOOK_SCHEMA_NAMES,
    RESOURCE_TO_CIO_OBJECT_TYPE,
)
from posthog.temporal.data_imports.sources.customer_io.source import CustomerIOSource
from posthog.temporal.data_imports.sources.generated_configs import CustomerIOSourceConfig


def _config(app_api_key: str = "test-key", region: Literal["us", "eu"] = "us") -> CustomerIOSourceConfig:
    return CustomerIOSourceConfig(app_api_key=app_api_key, region=region)


class TestCustomerIOSourceConfigFields:
    def test_get_source_config_exposes_required_app_api_key_and_region(self):
        source = CustomerIOSource()
        cfg = source.get_source_config

        names = {f.name for f in cfg.fields}
        assert names == {"app_api_key", "region"}

        api_key_field = next(f for f in cfg.fields if f.name == "app_api_key")
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.required is True
        assert api_key_field.secret is True

        region_field = next(f for f in cfg.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.required is True
        assert region_field.defaultValue == "us"
        assert {opt.value for opt in region_field.options} == {"us", "eu"}


class TestCustomerIOSourceWebhookResourceMap:
    def test_keys_use_events_suffix_and_map_to_cio_object_types(self):
        source = CustomerIOSource()
        mapping = source.webhook_resource_map

        for schema_name in mapping:
            assert schema_name.endswith("_events"), schema_name

        assert mapping["customer_events"] == "customer"
        assert mapping["email_events"] == "email"
        assert mapping["in_app_events"] == "in_app"


class TestCustomerIOSourceGetSchemas:
    def test_includes_both_webhook_and_api_schemas(self):
        source = CustomerIOSource()

        schemas = source.get_schemas(_config(), team_id=1)

        names = {s.name for s in schemas}
        for name in CIO_WEBHOOK_SCHEMA_NAMES:
            assert name in names, f"missing webhook schema: {name}"
        for name in CIO_API_SCHEMA_NAMES:
            assert name in names, f"missing api schema: {name}"

    def test_filters_by_names_argument(self):
        source = CustomerIOSource()

        schemas = source.get_schemas(_config(), team_id=1, names=["broadcasts", "email_events"])

        assert {s.name for s in schemas} == {"broadcasts", "email_events"}

    def test_only_event_schemas_support_webhooks(self):
        source = CustomerIOSource()

        schemas = source.get_schemas(_config(), team_id=1)

        webhook_supported = {s.name for s in schemas if s.supports_webhooks}
        assert webhook_supported == set(CIO_WEBHOOK_SCHEMA_NAMES)


class TestCustomerIOSourceCreateWebhook:
    @patch("posthog.temporal.data_imports.sources.customer_io.source.api_client.create_webhook")
    def test_delegates_to_api_client(self, mock_create):
        mock_create.return_value = WebhookCreationResult(success=True, pending_inputs=["signing_secret"])
        source = CustomerIOSource()

        result = source.create_webhook(_config(app_api_key="key", region="eu"), "https://example.com/h", team_id=1)

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["region"] == "eu"
        assert kwargs["webhook_url"] == "https://example.com/h"
        # All Customer.io webhook schema names should be passed through.
        assert set(kwargs["resource_names"]) == set(RESOURCE_TO_CIO_OBJECT_TYPE.keys())


class TestCustomerIOSourceDeleteWebhook:
    @patch("posthog.temporal.data_imports.sources.customer_io.source.api_client.delete_webhook")
    def test_delegates_to_api_client(self, mock_delete):
        mock_delete.return_value = WebhookDeletionResult(success=True)
        source = CustomerIOSource()

        result = source.delete_webhook(_config(app_api_key="key", region="us"), "https://example.com/h", team_id=1)

        assert result.success is True
        mock_delete.assert_called_once_with("key", "us", "https://example.com/h")


class TestCustomerIOSourceExternalWebhookInfo:
    @patch("posthog.temporal.data_imports.sources.customer_io.source.api_client.get_external_webhook_info")
    def test_delegates_to_api_client(self, mock_info):
        mock_info.return_value = ExternalWebhookInfo(exists=True, status="enabled")
        source = CustomerIOSource()

        info = source.get_external_webhook_info(
            _config(app_api_key="key", region="eu"), "https://example.com/h", team_id=1
        )

        assert info is not None
        assert info.exists is True
        mock_info.assert_called_once_with("key", "eu", "https://example.com/h")


class TestCustomerIOSourceValidateCredentials:
    @patch("posthog.temporal.data_imports.sources.customer_io.source.api_client.validate_credentials")
    def test_delegates_to_api_client(self, mock_validate):
        mock_validate.return_value = (True, None)
        source = CustomerIOSource()

        success, error = source.validate_credentials(_config(app_api_key="key", region="us"), team_id=1)

        assert success is True
        assert error is None
        mock_validate.assert_called_once_with("key", "us")


class TestCustomerIOSourcePipelineDispatch:
    @patch("posthog.temporal.data_imports.sources.customer_io.source.api_client.iterate_list_endpoint")
    def test_api_schema_routes_to_iterate_list_endpoint(self, mock_iter):
        mock_iter.return_value = iter([{"id": 1}, {"id": 2}])
        source = CustomerIOSource()
        inputs = MagicMock()
        inputs.schema_name = "broadcasts"
        inputs.logger = MagicMock()

        response = source.source_for_pipeline(_config(app_api_key="key", region="us"), inputs)

        assert response.name == "broadcasts"
        assert response.primary_keys == ["id"]

        # Verify the items() iterator triggers iterate_list_endpoint with the right endpoint.
        rows = list(cast(Iterable[dict[str, int]], response.items()))
        assert rows == [{"id": 1}, {"id": 2}]
        mock_iter.assert_called_once()
        kwargs = mock_iter.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"].path == "/v1/broadcasts"

    def test_webhook_schema_routes_to_webhook_source_response(self):
        source = CustomerIOSource()
        inputs = MagicMock()
        inputs.schema_name = "email_events"
        inputs.logger = MagicMock()

        sentinel = cast(SourceResponse, "WEBHOOK_RESPONSE")
        # Stub the webhook manager so we don't need a real one.
        with patch.object(source, "_webhook_source_response", return_value=sentinel) as mock_webhook:
            result = source.source_for_pipeline(_config(app_api_key="key"), inputs)

        assert result is sentinel
        mock_webhook.assert_called_once_with(inputs)

    @patch("posthog.temporal.data_imports.sources.customer_io.source.api_client.iterate_list_endpoint")
    def test_datetime_partitioned_endpoint(self, mock_iter):
        mock_iter.return_value = iter([])
        source = CustomerIOSource()
        inputs = MagicMock()
        inputs.schema_name = "broadcasts"
        inputs.logger = MagicMock()

        response = source.source_for_pipeline(_config(app_api_key="key"), inputs)

        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["created"]

    @patch("posthog.temporal.data_imports.sources.customer_io.source.api_client.iterate_list_endpoint")
    def test_md5_partitioned_endpoint(self, mock_iter):
        mock_iter.return_value = iter([])
        source = CustomerIOSource()
        inputs = MagicMock()
        inputs.schema_name = "snippets"
        inputs.logger = MagicMock()

        response = source.source_for_pipeline(_config(app_api_key="key"), inputs)

        # snippets have no created/created_at, so we partition by hashing `name`.
        assert response.partition_mode == "md5"
        assert response.partition_keys == ["name"]
        assert response.partition_format is None

    def test_every_api_endpoint_has_partitioning_configured(self):
        from posthog.temporal.data_imports.sources.customer_io.constants import CIO_API_ENDPOINTS

        for name, endpoint in CIO_API_ENDPOINTS.items():
            assert endpoint.partition_mode in ("datetime", "md5"), name
            assert endpoint.partition_keys, name
            if endpoint.partition_mode == "datetime":
                assert endpoint.partition_format is not None, name

    def test_messages_schema_is_not_exposed(self):
        # Excluded because the webhook event tables already cover per-delivery activity.
        source = CustomerIOSource()

        schemas = source.get_schemas(_config(), team_id=1)

        assert "messages" not in {s.name for s in schemas}
