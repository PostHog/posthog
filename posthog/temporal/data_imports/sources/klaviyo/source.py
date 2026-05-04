from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import KlaviyoSourceConfig
from posthog.temporal.data_imports.sources.klaviyo.klaviyo import (
    KlaviyoResumeConfig,
    klaviyo_source,
    validate_credentials as validate_klaviyo_credentials,
)
from posthog.temporal.data_imports.sources.klaviyo.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KlaviyoSource(ResumableSource[KlaviyoSourceConfig, KlaviyoResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KLAVIYO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KLAVIYO,
            label="Klaviyo",
            releaseStatus="beta",
            caption="""Enter your Klaviyo API key to automatically pull your Klaviyo data into the PostHog Data warehouse.

You can create a private API key in your [Klaviyo account settings](https://www.klaviyo.com/settings/account/api-keys).

Make sure to grant the following read permissions:
- Accounts
- Campaigns
- Events
- Flows
- Lists
- Metrics
- Profiles
""",
            iconPath="/static/services/klaviyo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/klaviyo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self, config: KlaviyoSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        # Events are immutable - append-only is the only sync mode
        append_only_endpoints = {"events"}

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None
                and endpoint not in append_only_endpoints,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description="Only syncs the last 365 days on initial sync" if endpoint == "events" else None,
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: KlaviyoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_klaviyo_credentials(config.api_key):
            return True, None

        return False, "Invalid Klaviyo API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KlaviyoResumeConfig]:
        return ResumableSourceManager[KlaviyoResumeConfig](inputs, KlaviyoResumeConfig)

    def source_for_pipeline(
        self,
        config: KlaviyoSourceConfig,
        resumable_source_manager: ResumableSourceManager[KlaviyoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return klaviyo_source(
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
