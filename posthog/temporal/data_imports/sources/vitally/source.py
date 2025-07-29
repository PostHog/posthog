import re
from typing import cast
from posthog.schema import (
    ExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldSelectConfig,
    Type4,
    Option,
)
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.vitally.vitally import (
    validate_credentials as validate_vitally_credentials,
    vitally_source,
)
from posthog.temporal.data_imports.sources.vitally.settings import (
    ENDPOINTS as VITALLY_ENDPOINTS,
    INCREMENTAL_FIELDS as VITALLY_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.utils import dlt_source_to_source_response
from posthog.temporal.data_imports.sources.generated_configs import VitallySourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class VitallySource(BaseSource[VitallySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.VITALLY

    def get_schemas(self, config: VitallySourceConfig, team_id: int) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=VITALLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=VITALLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=VITALLY_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in VITALLY_ENDPOINTS
        ]

    def validate_credentials(self, config: VitallySourceConfig, team_id: int) -> tuple[bool, str | None]:
        subdomain_regex = re.compile("^[a-zA-Z-]+$")
        if config.region.selection == "US" and not subdomain_regex.match(config.region.subdomain):
            return False, "Vitally subdomain is incorrect"

        if validate_vitally_credentials(config.secret_token, config.region.selection, config.region.subdomain):
            return True, None

        return False, "Invalid credentials"

    def source_for_pipeline(self, config: VitallySourceConfig, inputs: SourceInputs) -> SourceResponse:
        return dlt_source_to_source_response(
            vitally_source(
                secret_token=config.secret_token,
                region=config.region.selection,
                subdomain=config.region.subdomain,
                endpoint=inputs.schema_name,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VITALLY,
            caption="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_token",
                        label="Secret token",
                        type=Type4.TEXT,
                        required=True,
                        placeholder="sk_live_...",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Vitally region",
                        required=True,
                        defaultValue="EU",
                        options=[
                            Option(label="EU", value="EU"),
                            Option(
                                label="US",
                                value="US",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="subdomain",
                                            label="Vitally subdomain",
                                            type=Type4.TEXT,
                                            required=True,
                                            placeholder="",
                                        )
                                    ],
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )
