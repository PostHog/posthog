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
from posthog.temporal.data_imports.sources.generated_configs import RechargeSourceConfig
from posthog.temporal.data_imports.sources.recharge.recharge import (
    RechargeResumeConfig,
    recharge_source,
    validate_credentials as validate_recharge_credentials,
)
from posthog.temporal.data_imports.sources.recharge.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RechargeSource(ResumableSource[RechargeSourceConfig, RechargeResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RECHARGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RECHARGE,
            label="Recharge",
            caption="""Enter your Recharge API token to automatically pull your Recharge subscription data into the PostHog Data warehouse.

You can create an API token in your [Recharge admin](https://docs.getrecharge.com/docs/recharge-api-and-developer-tools) under **Apps & integrations > API tokens**.

Grant **read** access to the resources you want to sync, e.g.:
- Customers
- Subscriptions
- Orders
- Charges
- Addresses
- Discounts
- Products

Some resources (such as Payment methods) are only available on Recharge Pro or Custom plans.
""",
            iconPath="/static/services/recharge.png",
            docsUrl="https://posthog.com/docs/cdp/sources/recharge",
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Recharge rejected the API token. Generate a new token and reconnect.",
            "403 Client Error: Forbidden": (
                "The Recharge API token is missing the permissions required for this resource. "
                "Grant read access to the resource and reconnect."
            ),
        }

    def get_schemas(
        self,
        config: RechargeSourceConfig,
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
        self, config: RechargeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_recharge_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RechargeResumeConfig]:
        return ResumableSourceManager[RechargeResumeConfig](inputs, RechargeResumeConfig)

    def source_for_pipeline(
        self,
        config: RechargeSourceConfig,
        resumable_source_manager: ResumableSourceManager[RechargeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return recharge_source(
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
