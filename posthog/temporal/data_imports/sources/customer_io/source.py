from collections.abc import AsyncIterable, Iterable
from typing import TYPE_CHECKING, Any, Optional, cast

from asgiref.sync import async_to_sync

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from posthog.temporal.data_imports.sources.common.webhook_s3 import (
    WebhookSourceManager,
    is_webhook_feature_flag_enabled,
)
from posthog.temporal.data_imports.sources.customer_io.constants import CIO_ENDPOINTS, RESOURCE_TO_CIO_OBJECT_TYPE
from posthog.temporal.data_imports.sources.generated_configs import CustomerIOSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


CIO_DOCS_WEBHOOKS_URL = "https://fly.customer.io/settings/webhooks/new/reporting_webhook"


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
                "Connect your Customer.io account by sending reporting webhooks to PostHog. "
                f"Create a reporting webhook in [Customer.io]({CIO_DOCS_WEBHOOKS_URL}) and "
                "complete the signing key step during webhook setup."
            ),
            iconPath="/static/services/customer-io.png",
            label="Customer.io",
            docsUrl="https://posthog.com/docs/cdp/sources/customer-io",
            fields=cast(list[FieldType], []),
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-customer-io",
            webhookSetupCaption="""To set up the webhook manually:

1. Go to your [Customer.io workspace > Data & Integrations > Integrations > Reporting Webhooks](https://fly.customer.io/settings/webhooks/new/reporting_webhook)
2. Click **Add Reporting Webhook**
3. Paste the webhook URL shown below into the **Endpoint URL** field
4. Select the events you want to track (email, push, sms, in-app, slack, webhook, customer)
5. Use **Selected events** or **All events** as appropriate
6. Click **Save**

Once created, copy the **Signing key** from the webhook details page and add it to your source configuration for signature verification.""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Customer.io reporting webhook signing key",
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: CustomerIOSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Customer.io has no API credentials for this source — the user only provides the
        # webhook signing key via webhookFields at webhook setup time. Nothing to validate up front.
        return True, None

    def get_schemas(
        self,
        config: CustomerIOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        webhooks_enabled = is_webhook_feature_flag_enabled(team_id)
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=True,
                supports_webhooks=webhooks_enabled,
                incremental_fields=[],
            )
            for endpoint in CIO_ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: CustomerIOSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        return WebhookCreationResult(
            success=False,
            error="Customer.io webhooks must be created manually in the Customer.io dashboard.",
        )

    def get_external_webhook_info(
        self, config: CustomerIOSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo | None:
        return None

    def delete_webhook(self, config: CustomerIOSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        return WebhookDeletionResult(
            success=False,
            error="Customer.io webhooks must be deleted manually in the Customer.io dashboard.",
        )

    def source_for_pipeline(self, config: CustomerIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        webhook_source_manager = self.get_webhook_source_manager(inputs)
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

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
