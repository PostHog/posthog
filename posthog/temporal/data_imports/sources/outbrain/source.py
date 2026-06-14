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
from posthog.temporal.data_imports.sources.generated_configs import OutbrainSourceConfig
from posthog.temporal.data_imports.sources.outbrain.outbrain import (
    OutbrainResumeConfig,
    outbrain_source,
    validate_credentials as validate_outbrain_credentials,
)
from posthog.temporal.data_imports.sources.outbrain.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OutbrainSource(ResumableSource[OutbrainSourceConfig, OutbrainResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OUTBRAIN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.outbrain.com/amplify/v0.1/login": "Outbrain authentication failed. Please check your username and password.",
            "403 Client Error: Forbidden for url: https://api.outbrain.com": "Outbrain denied access. Please check that your account has Amplify API access (requested via your account manager).",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OUTBRAIN,
            label="Outbrain",
            caption="""Connect your Outbrain Amplify account to pull your advertising data into the PostHog Data warehouse.

Uses your Outbrain login credentials. Amplify API access must be enabled for your account — request it through your Outbrain account manager if API calls are rejected.""",
            iconPath="/static/services/outbrain.png",
            docsUrl="https://posthog.com/docs/cdp/sources/outbrain",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="username",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="user@company.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
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
        config: OutbrainSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: OutbrainSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_outbrain_credentials(config.username, config.password):
            return True, None

        return False, "Invalid Outbrain credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OutbrainResumeConfig]:
        return ResumableSourceManager[OutbrainResumeConfig](inputs, OutbrainResumeConfig)

    def source_for_pipeline(
        self,
        config: OutbrainSourceConfig,
        resumable_source_manager: ResumableSourceManager[OutbrainResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return outbrain_source(
            username=config.username,
            password=config.password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
