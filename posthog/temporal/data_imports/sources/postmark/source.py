from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import PostmarkSourceConfig
from posthog.temporal.data_imports.sources.postmark.postmark import (
    postmark_source,
    validate_credentials as validate_postmark_credentials,
)
from posthog.temporal.data_imports.sources.postmark.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PostmarkSource(SimpleSource[PostmarkSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTMARK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POSTMARK,
            label="Postmark",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh_postmark",
            caption="""Enter your Postmark Server API token to automatically pull message activity, opens, clicks, bounces, and more into the PostHog Data warehouse.

You can find your Server API token in the Postmark UI under your server's **API Tokens** tab.

Note: outbound message search is limited to a 45-day window per Postmark's API; sync incrementally to keep history flowing in.
""",
            iconPath="/static/services/postmark.png",
            docsUrl="https://posthog.com/docs/cdp/sources/postmark",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="server_api_token",
                        label="Server API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="abcdefgh-1234-5678-90ab-cdef12345678",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Postmark Server API token. Please check the token and reconnect.",
            "403 Client Error": "Your Postmark Server API token is missing required permissions.",
            "422 Client Error": "Postmark rejected the request. A common cause is requesting a date range outside the 45-day search window for outbound messages.",
        }

    def get_schemas(
        self, config: PostmarkSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PostmarkSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_postmark_credentials(config.server_api_token)

    def source_for_pipeline(self, config: PostmarkSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return postmark_source(
            server_token=config.server_api_token,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
