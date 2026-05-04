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
from posthog.temporal.data_imports.sources.generated_configs import ResendSourceConfig
from posthog.temporal.data_imports.sources.resend.resend import (
    ResendResumeConfig,
    resend_source,
    validate_credentials as validate_resend_credentials,
)
from posthog.temporal.data_imports.sources.resend.settings import ENDPOINTS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ResendSource(ResumableSource[ResendSourceConfig, ResendResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RESEND

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RESEND,
            label="Resend",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Resend API key to pull your Resend data into the PostHog Data warehouse.

You can create an API key in your [Resend API keys settings](https://resend.com/api-keys).

Grant the key **full access** or a read-enabled access token so the following resources can be read:
- Audiences
- Broadcasts
- Contacts
- Domains
- Emails
""",
            iconPath="/static/services/resend.png",
            docsUrl="https://posthog.com/docs/cdp/sources/resend",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="re_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self, config: ResendSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        # Resend's API does not expose server-side filters on created_at; sync as
        # full-refresh only. Within-sync resumption is handled by ResumableSource.
        schemas = [
            SourceSchema(name=endpoint, supports_incremental=False, supports_append=False, incremental_fields=[])
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ResendSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_resend_credentials(config.api_key):
            return True, None

        return False, "Invalid Resend API key"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.resend.com": (
                "Your Resend API key is invalid or expired. Please generate a new key and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.resend.com": (
                "Your Resend API key does not have the required permissions. Please check the key permissions and try again."
            ),
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ResendResumeConfig]:
        return ResumableSourceManager[ResendResumeConfig](inputs, ResendResumeConfig)

    def source_for_pipeline(
        self,
        config: ResendSourceConfig,
        resumable_source_manager: ResumableSourceManager[ResendResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return resend_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
