from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import IncidentIoSourceConfig
from posthog.temporal.data_imports.sources.incident_io.incident_io import (
    IncidentIoResumeConfig,
    incident_io_source,
    validate_credentials as validate_incident_io_credentials,
)
from posthog.temporal.data_imports.sources.incident_io.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IncidentIoSource(ResumableSource[IncidentIoSourceConfig, IncidentIoResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INCIDENTIO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.incident.io": "incident.io authentication failed. Please check that your API key is valid and has not been revoked.",
            "403 Client Error: Forbidden for url: https://api.incident.io": "Your incident.io API key is missing a required permission. incident.io API keys have per-resource permissions — grant the key the 'view' scope for the resources you want to sync.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INCIDENT_IO,
            label="incident.io",
            caption="""Enter your incident.io API key to pull your incident data into the PostHog Data warehouse.

You can create an API key in your [incident.io dashboard](https://app.incident.io/settings/api-keys). API keys have per-resource permissions — grant the `view` scope for each resource you want to sync (incidents, follow-ups, alerts, users, and so on).""",
            iconPath="/static/services/incident_io.png",
            docsUrl="https://posthog.com/docs/cdp/sources/incident-io",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: IncidentIoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: IncidentIoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_incident_io_credentials(config.api_key, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[IncidentIoResumeConfig]:
        return ResumableSourceManager[IncidentIoResumeConfig](inputs, IncidentIoResumeConfig)

    def source_for_pipeline(
        self,
        config: IncidentIoSourceConfig,
        resumable_source_manager: ResumableSourceManager[IncidentIoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return incident_io_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
