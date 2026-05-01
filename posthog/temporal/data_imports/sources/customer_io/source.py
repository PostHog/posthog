from collections.abc import AsyncIterable, Iterable
from typing import TYPE_CHECKING, Any, Optional, cast

from asgiref.sync import async_to_sync

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    FieldType,
    SimpleSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
)
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from posthog.temporal.data_imports.sources.customer_io import api_client
from posthog.temporal.data_imports.sources.customer_io.constants import (
    CIO_API_ENDPOINTS,
    CIO_API_SCHEMA_NAMES,
    CIO_WEBHOOK_SCHEMA_NAMES,
    RESOURCE_TO_CIO_OBJECT_TYPE,
)
from posthog.temporal.data_imports.sources.generated_configs import CustomerIOSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


CIO_DOCS_WEBHOOKS_URL = "https://fly.customer.io/settings/webhooks/new/reporting_webhook"
CIO_APP_API_KEY_URL = "https://fly.customer.io/settings/api_credentials?keyType=app"


@SourceRegistry.register
class CustomerIOSource(
    SimpleSource[CustomerIOSourceConfig],
    WebhookSource[CustomerIOSourceConfig],
):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CUSTOMERIO

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from posthog.temporal.data_imports.sources.customer_io.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_CIO_OBJECT_TYPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CUSTOMER_IO,
            caption=(
                "Connect your Customer.io workspace using an "
                f"[App API Key]({CIO_APP_API_KEY_URL}). PostHog uses the key to pull "
                "campaigns, broadcasts, segments, newsletters, and more, and to register "
                "a reporting webhook for realtime message activity."
            ),
            iconPath="/static/services/customer-io.png",
            label="Customer.io",
            docsUrl="https://posthog.com/docs/cdp/sources/customer-io",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_api_key",
                        label="App API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Customer.io App API Key",
                        caption=(
                            f"Generate a key under [API Credentials > App API Keys]({CIO_APP_API_KEY_URL}). "
                            "PostHog needs this key both for pulling list endpoints and for managing the "
                            "reporting webhook automatically."
                        ),
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.customer.io)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api-eu.customer.io)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-customer-io",
            webhookSetupCaption=(
                "PostHog tries to register the reporting webhook for you using your App API Key. "
                "Customer.io doesn't return the signing key in the API response, so you still need "
                "to copy it from the **Reporting Webhooks** page in Customer.io and paste it below."
                "\n\nGo to your **Customer.io workspace** > **Integrations** > **Reporting Webhooks** > **{CIO_AUTO_WEBHOOK_NAME}**\n\n\n"
                "**Manual setup** (only needed if auto-registration failed):\n\n"
                "1. Go to your **Customer.io workspace** > **Integrations** > **Add Integration**\n"
                "2. Search for **Reporting Webhook**\n"
                "3. Paste the webhook URL shown below into the **Webhook endpoint** field\n"
                "4. Select the events you want to track (customer, email, push, sms, in-app, slack, webhook)\n"
                "5. Click **Save and Enable Webhook**\n\n"
                "Then copy the **Signing key** from the webhook details page into the field below."
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Customer.io reporting webhook signing key",
                        secret=True,
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: CustomerIOSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return api_client.validate_credentials(config.app_api_key, config.region)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "Customer.io rejected the App API Key. Generate a new key from Settings > API "
                "Credentials > App API Keys and reconnect."
            ),
            "403 Client Error: Forbidden": (
                "The App API Key doesn't have permission for this endpoint. Make sure the key has "
                "access to the resources you're syncing."
            ),
        }

    def get_schemas(
        self,
        config: CustomerIOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        # `supports_append=False` on the webhook schemas: events arrive via the realtime
        # webhook pipeline (not the polling sync), so user-facing append/full-refresh
        # toggles don't apply. The polling sync would also have nothing to fetch from
        # the API for these — they're webhook-only.
        webhook_schemas = [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=True,
                incremental_fields=[],
            )
            for name in CIO_WEBHOOK_SCHEMA_NAMES
        ]
        # API list endpoints are full-refresh: the App API doesn't expose a
        # server-side time filter on `created_at`, so an "append" sync would still
        # have to read every row each run.
        api_schemas = [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=False,
                incremental_fields=[],
            )
            for name in CIO_API_SCHEMA_NAMES
        ]
        schemas = [*webhook_schemas, *api_schemas]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: CustomerIOSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        return api_client.create_webhook(
            api_key=config.app_api_key,
            region=config.region,
            webhook_url=webhook_url,
            resource_names=list(RESOURCE_TO_CIO_OBJECT_TYPE.keys()),
        )

    def get_external_webhook_info(
        self, config: CustomerIOSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo | None:
        return api_client.get_external_webhook_info(config.app_api_key, config.region, webhook_url)

    def delete_webhook(self, config: CustomerIOSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        return api_client.delete_webhook(config.app_api_key, config.region, webhook_url)

    def source_for_pipeline(self, config: CustomerIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name in CIO_API_ENDPOINTS:
            return self._api_source_response(config, inputs)
        return self._webhook_source_response(inputs)

    def _webhook_source_response(self, inputs: SourceInputs) -> SourceResponse:
        webhook_source_manager = self.get_webhook_source_manager(inputs)
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(True)

        def items() -> Iterable[Any] | AsyncIterable[Any]:
            if webhook_enabled:
                return webhook_source_manager.get_items()
            return iter([])

        return SourceResponse(
            items=items,
            primary_keys=["event_id"],
            name=inputs.schema_name,
            sort_mode="asc",
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            partition_keys=["timestamp"],
        )

    def _api_source_response(self, config: CustomerIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        endpoint = CIO_API_ENDPOINTS[inputs.schema_name]

        def items() -> Iterable[Any]:
            yield from api_client.iterate_list_endpoint(
                api_key=config.app_api_key,
                region=config.region,
                endpoint=endpoint,
            )

        return SourceResponse(
            items=items,
            primary_keys=endpoint.primary_keys,
            name=inputs.schema_name,
            partition_keys=endpoint.partition_keys,
            partition_mode=endpoint.partition_mode,
            partition_format=endpoint.partition_format,
            partition_count=endpoint.partition_count,
            partition_size=endpoint.partition_size,
        )
