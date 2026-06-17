from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
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
from posthog.temporal.data_imports.sources.crunchbase.crunchbase import (
    CrunchbaseResumeConfig,
    crunchbase_source,
    validate_credentials as validate_crunchbase_credentials,
)
from posthog.temporal.data_imports.sources.crunchbase.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.generated_configs import CrunchbaseSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CrunchbaseSource(ResumableSource[CrunchbaseSourceConfig, CrunchbaseResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRUNCHBASE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.crunchbase.com": "Crunchbase authentication failed. Please check your user key.",
            "403 Client Error: Forbidden for url: https://api.crunchbase.com": "Crunchbase denied access. The Search API requires a Crunchbase Enterprise or Applications license.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CRUNCHBASE,
            category=DataWarehouseSourceCategory.CRM,
            label="Crunchbase",
            caption="""Enter your Crunchbase user key to pull Crunchbase company and funding data into the PostHog Data warehouse.

You can find your user key in [Crunchbase account settings](https://www.crunchbase.com/account/integrations/crunchbase-api). Note that the Search API used for syncing requires a Crunchbase Enterprise or Applications license.""",
            iconPath="/static/services/crunchbase.png",
            docsUrl="https://posthog.com/docs/cdp/sources/crunchbase",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="User key",
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
        config: CrunchbaseSourceConfig,
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
        self, config: CrunchbaseSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_crunchbase_credentials(config.api_key):
            return True, None

        return False, "Invalid Crunchbase user key, or the key lacks Search API (Enterprise/Applications) access"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CrunchbaseResumeConfig]:
        return ResumableSourceManager[CrunchbaseResumeConfig](inputs, CrunchbaseResumeConfig)

    def source_for_pipeline(
        self,
        config: CrunchbaseSourceConfig,
        resumable_source_manager: ResumableSourceManager[CrunchbaseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return crunchbase_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
