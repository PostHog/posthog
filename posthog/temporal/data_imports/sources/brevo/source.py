from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.brevo.brevo import (
    BrevoResumeConfig,
    brevo_source,
    validate_credentials as validate_brevo_credentials,
)
from posthog.temporal.data_imports.sources.brevo.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import BrevoSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrevoSource(ResumableSource[BrevoSourceConfig, BrevoResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BREVO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Brevo authentication failed. Your API key is invalid or expired - please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url": "Your Brevo API key does not have the required permissions. Please check the key and reconnect.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BREVO,
            label="Brevo",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Brevo API key to automatically pull your Brevo (formerly Sendinblue) data into the PostHog Data warehouse.

You can create an API key in your [Brevo account settings](https://app.brevo.com/settings/keys/api).""",
            iconPath="/static/services/brevo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/brevo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="xkeysib-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: BrevoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=(fields := INCREMENTAL_FIELDS.get(endpoint)) is not None,
                supports_append=fields is not None,
                incremental_fields=fields or [],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: BrevoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_brevo_credentials(config.api_key):
            return True, None

        return False, "Invalid Brevo API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BrevoResumeConfig]:
        return ResumableSourceManager[BrevoResumeConfig](inputs, BrevoResumeConfig)

    def source_for_pipeline(
        self,
        config: BrevoSourceConfig,
        resumable_source_manager: ResumableSourceManager[BrevoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return brevo_source(
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
