import re
from typing import cast
from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema

from posthog.temporal.data_imports.sources.zendesk.settings import (
    BASE_ENDPOINTS,
    INCREMENTAL_FIELDS as ZENDESK_INCREMENTAL_FIELDS,
    SUPPORT_ENDPOINTS,
)
from posthog.temporal.data_imports.sources.zendesk.zendesk import zendesk_source, validate_credentials
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.utils import dlt_source_to_source_response
from posthog.temporal.data_imports.sources.generated_configs import ZendeskSourceConfig
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class ZendeskSource(BaseSource[ZendeskSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENDESK

    def get_schemas(self, config: ZendeskSourceConfig, team_id: int) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=ZENDESK_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(BASE_ENDPOINTS)
            + [resource for resource, endpoint_url, data_key, cursor_paginated in SUPPORT_ENDPOINTS]
        ]

    def validate_credentials(self, config: ZendeskSourceConfig, team_id: int) -> tuple[bool, str | None]:
        subdomain_regex = re.compile("^[a-zA-Z0-9-]+$")
        if not subdomain_regex.match(config.subdomain):
            return False, "Zendesk subdomain is incorrect"

        if validate_credentials(config.subdomain, config.api_key, config.email_address):
            return True, None

        return False, "Invalid credentials"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZENDESK,
            caption="Enter your Zendesk API key to automatically pull your Zendesk support data into the PostHog Data warehouse.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Zendesk subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="email_address",
                        label="Zendesk email address",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="",
                    ),
                ],
            ),
        )

    def source_for_pipeline(self, config: ZendeskSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return dlt_source_to_source_response(
            zendesk_source(
                subdomain=config.subdomain,
                api_key=config.api_key,
                email_address=config.email_address,
                endpoint=inputs.schema_name,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        )
