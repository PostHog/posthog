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
from posthog.temporal.data_imports.sources.generated_configs import PolarSourceConfig
from posthog.temporal.data_imports.sources.polar.polar import (
    PolarPermissionError,
    PolarResumeConfig,
    polar_source,
    validate_credentials as validate_polar_credentials,
)
from posthog.temporal.data_imports.sources.polar.settings import (
    ENDPOINTS as POLAR_ENDPOINTS,
    INCREMENTAL_FIELDS as POLAR_INCREMENTAL_FIELDS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PolarSource(ResumableSource[PolarSourceConfig, PolarResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POLAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POLAR,
            label="Polar",
            caption=(
                "Connect your Polar.sh account using an "
                "[Organization Access Token](https://docs.polar.sh/integrate/oat) "
                "to sync customers, products, orders, subscriptions, and more."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/polar",
            iconPath="/static/services/polar.png",
            iconClassName="rounded dark:bg-white p-[2px]",
            featureFlag="dwh_polar",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="polar_api_key",
                        label="Organization Access Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="polar_oat_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.polar.sh": "Your Polar Organization Access Token is invalid or expired. Please generate a new token in Polar and reconnect.",
            "403 Client Error: Forbidden for url: https://api.polar.sh": "Your Polar Organization Access Token does not have the required permissions. Please check the token's scopes in Polar and reconnect.",
        }

    def should_retry_non_retryable_errors(self) -> bool:
        return False

    def validate_credentials(
        self, config: PolarSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            if validate_polar_credentials(config.polar_api_key, schema_name):
                return True, None
            else:
                return False, "Invalid Polar Organization Access Token"
        except PolarPermissionError as e:
            return False, f"Polar Organization Access Token lacks permissions: {e}"
        except Exception as e:
            return False, str(e)

    def get_schemas(
        self, config: PolarSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(POLAR_INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(POLAR_INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=POLAR_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in POLAR_ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PolarResumeConfig]:
        return ResumableSourceManager[PolarResumeConfig](inputs, PolarResumeConfig)

    def source_for_pipeline(
        self,
        config: PolarSourceConfig,
        resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return polar_source(
            api_key=config.polar_api_key,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
