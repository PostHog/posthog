from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import NotionSourceConfig
from posthog.temporal.data_imports.sources.notion.helpers import validate_credentials
from posthog.temporal.data_imports.sources.notion.notion import notion_source
from posthog.temporal.data_imports.sources.notion.settings import ENDPOINTS, INCREMENTAL_ENDPOINTS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NotionSource(SimpleSource[NotionSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOTION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NOTION,
            caption="Select an existing Notion account to link to PostHog or create a new connection",
            iconPath="/static/services/notion.png",
            docsUrl="https://posthog.com/docs/cdp/sources/notion",
            feature_flag="dwh_notion",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="notion_integration_id", label="Notion account", required=True, kind="notion"
                    )
                ],
            ),
        )

    def validate_credentials(self, config: NotionSourceConfig, team_id: int) -> tuple[bool, str | None]:
        integration = self.get_oauth_integration(config.notion_integration_id, team_id)

        if not integration.access_token:
            return False, "Notion access token not found"

        if validate_credentials(integration.access_token):
            return True, None

        return False, "Invalid Notion credentials"

    def get_schemas(self, config: NotionSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_ENDPOINTS,
                supports_append=endpoint in INCREMENTAL_ENDPOINTS,
                incremental_fields=[INCREMENTAL_ENDPOINTS[endpoint]] if endpoint in INCREMENTAL_ENDPOINTS else [],
            )
            for endpoint in ENDPOINTS
        ]

    def source_for_pipeline(self, config: NotionSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.notion_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Notion access token not found for job {inputs.job_id}")

        # Determine the incremental field value based on endpoint
        incremental_field_value = None
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value:
            incremental_field_value = inputs.db_incremental_field_last_value

        # Map endpoint to correct parameter name
        kwargs = {}
        if inputs.schema_name == "comments":
            kwargs["created_time"] = incremental_field_value
        elif inputs.schema_name in INCREMENTAL_ENDPOINTS:
            kwargs["last_edited_time"] = incremental_field_value

        items = notion_source(
            access_token=integration.access_token,
            endpoint=inputs.schema_name,
            **kwargs,
        )

        # Determine partition keys based on endpoint
        partition_keys = None
        if inputs.schema_name == "comments":
            partition_keys = ["created_time"]
        elif inputs.schema_name in INCREMENTAL_ENDPOINTS:
            partition_keys = ["last_edited_time"]

        # Use id as primary key for all endpoints
        primary_keys = ["id"]

        return SourceResponse(
            items=items,
            primary_keys=primary_keys,
            partition_keys=partition_keys,
            partition_mode="datetime" if partition_keys else None,
        )
