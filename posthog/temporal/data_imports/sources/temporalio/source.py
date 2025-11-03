from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig
from posthog.temporal.data_imports.sources.temporalio.temporalio import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TemporalIOResource,
    temporalio_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TemporalIOSource(BaseSource[TemporalIOSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEMPORALIO

    def get_schemas(
        self, config: TemporalIOSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def source_for_pipeline(self, config: TemporalIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return temporalio_source(
            config,
            TemporalIOResource(inputs.schema_name),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEMPORAL_IO,
            label="Temporal.io",
            iconPath="/static/services/temporal.png",
            docsUrl="https://posthog.com/docs/cdp/sources/temporal",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host", label="Host", type=SourceFieldInputConfigType.TEXT, required=True, placeholder=""
                    ),
                    SourceFieldInputConfig(
                        name="port", label="Port", type=SourceFieldInputConfigType.TEXT, required=True, placeholder=""
                    ),
                    SourceFieldInputConfig(
                        name="namespace",
                        label="Namespace",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="encryption_key",
                        label="Encryption key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="server_client_root_ca",
                        label="Server client root CA",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="client_certificate",
                        label="Client certificate",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="client_private_key",
                        label="Client private key",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                    ),
                ],
            ),
        )
