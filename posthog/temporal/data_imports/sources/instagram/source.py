from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import InstagramSourceConfig
from posthog.temporal.data_imports.sources.instagram.instagram import InstagramResumeConfig, instagram_source
from posthog.temporal.data_imports.sources.instagram.schemas import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InstagramSource(ResumableSource[InstagramSourceConfig, InstagramResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INSTAGRAM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Failed to refresh token for Instagram integration. Please re-authorize the integration.": None,
            "(#10) Application does not have permission for this action": "Your Instagram integration is missing required scopes. Please reconnect.",
            "Error validating access token": "Your Instagram access token is invalid or expired. Please reconnect.",
            "Instagram account not found": None,
        }

    def validate_credentials(
        self, config: InstagramSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.ig_user_id or not config.instagram_integration_id:
            return False, "Instagram Business Account ID and Instagram integration are required"

        try:
            Integration.objects.get(id=config.instagram_integration_id, team_id=team_id)
            return True, None
        except Integration.DoesNotExist:
            return False, "Instagram integration not found. Please re-authenticate."
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Instagram credentials: {str(e)}"

    def get_schemas(
        self,
        config: InstagramSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
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

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InstagramResumeConfig]:
        return ResumableSourceManager[InstagramResumeConfig](inputs, InstagramResumeConfig)

    def source_for_pipeline(
        self,
        config: InstagramSourceConfig,
        resumable_source_manager: ResumableSourceManager[InstagramResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return instagram_source(
            resource_name=inputs.schema_name,
            config=config,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INSTAGRAM,
            label="Instagram",
            caption="Sync your Instagram Business or Creator account profile, media, stories, and account insights. Note: paid Instagram ad activity is covered by the separate Meta Ads source.",
            iconPath="/static/services/instagram.png",
            docsUrl="https://posthog.com/docs/cdp/sources/instagram",
            releaseStatus="alpha",
            featureFlag="dwh-instagram",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="ig_user_id",
                        label="Instagram Business Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="17841400000000000",
                        secret=False,
                    ),
                    SourceFieldOauthConfig(
                        name="instagram_integration_id",
                        label="Instagram account",
                        required=True,
                        kind="instagram",
                    ),
                    SourceFieldInputConfig(
                        name="sync_lookback_days",
                        label="Sync history for insights (days) - applies to user_insights",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="90",
                        secret=False,
                    ),
                ],
            ),
        )
