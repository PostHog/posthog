from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema

from posthog.temporal.data_imports.pipelines.source import config
from posthog.temporal.data_imports.pipelines.stripe import (
    stripe_source,
    validate_credentials as validate_stripe_credentials,
)
from posthog.temporal.data_imports.pipelines.stripe.settings import (
    ENDPOINTS as STRIPE_ENDPOINTS,
    INCREMENTAL_FIELDS as STRIPE_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.warehouse.models import ExternalDataSource


@config.config
class StripeSourceConfig(config.Config):
    stripe_secret_key: str
    stripe_account_id: str | None = None


@SourceRegistry.register
class StripeSource(BaseSource[StripeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.STRIPE

    @property
    def config_class(self) -> type[StripeSourceConfig]:
        return StripeSourceConfig

    def get_schemas(self, config: StripeSourceConfig) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=True,
                incremental_fields=STRIPE_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in STRIPE_ENDPOINTS
        ]

    def validate_credentials(self, config: StripeSourceConfig) -> bool:
        try:
            return validate_stripe_credentials(config.stripe_secret_key)
        except Exception:
            return False

    def source_for_pipeline(self, config: StripeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the stripe source func in here
        return stripe_source(
            api_key=config.stripe_secret_key,
            account_id=config.stripe_account_id,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
        )
