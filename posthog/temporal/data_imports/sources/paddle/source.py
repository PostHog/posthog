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
from posthog.temporal.data_imports.sources.generated_configs import PaddleSourceConfig
from posthog.temporal.data_imports.sources.paddle.paddle import (
    PaddlePermissionError,
    PaddleResumeConfig,
    paddle_source,
    validate_credentials as validate_paddle_credentials,
)
from posthog.temporal.data_imports.sources.paddle.settings import (
    ENDPOINTS as PADDLE_ENDPOINTS,
    INCREMENTAL_FIELDS as PADDLE_INCREMENTAL_FIELDS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PaddleSource(ResumableSource[PaddleSourceConfig, PaddleResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PADDLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PADDLE,
            label="Paddle",
            iconPath="/static/services/paddle.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="paddle_api_key",
                        label="API Key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pdl_live_...",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://api.paddle.com": "Paddle rejected the request parameters. Please check your source configuration and incremental sync state, then try again.",
            "401 Client Error: Unauthorized for url: https://api.paddle.com": "Your Paddle API key is invalid or expired. Please check your API key in Paddle and reconnect.",
            "403 Client Error: Forbidden for url: https://api.paddle.com": "Your Paddle API key does not have the required permissions. Please check your API key permissions in Paddle and try again.",
        }

    def should_retry_non_retryable_errors(self) -> bool:
        return False

    def validate_credentials(
        self, config: PaddleSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            if validate_paddle_credentials(config.paddle_api_key, schema_name):
                return True, None
            else:
                return False, "Invalid Paddle API key"
        except PaddlePermissionError as e:
            return False, f"Paddle API key lacks permissions: {e}"
        except Exception as e:
            return False, str(e)

    def get_schemas(
        self, config: PaddleSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(PADDLE_INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(PADDLE_INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=PADDLE_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in PADDLE_ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PaddleResumeConfig]:
        return ResumableSourceManager[PaddleResumeConfig](inputs, PaddleResumeConfig)

    def source_for_pipeline(
        self,
        config: PaddleSourceConfig,
        resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return paddle_source(
            api_key=config.paddle_api_key,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
