from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.models.integration import OauthIntegration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import NotionSourceConfig
from posthog.temporal.data_imports.sources.notion.notion import (
    NotionResumeConfig,
    _list_data_sources,
    notion_source,
    validate_credentials as validate_notion_credentials,
)
from posthog.temporal.data_imports.sources.notion.settings import (
    DATA_SOURCE_ROWS_PREFIX,
    INCREMENTAL_DATETIME_FIELDS,
    NOTION_STATIC_ENDPOINTS,
    STATIC_ENDPOINTS,
    data_source_rows_schema_name,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NotionSource(ResumableSource[NotionSourceConfig, NotionResumeConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOTION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NOTION,
            label="Notion",
            caption="Connect a Notion workspace to sync users, pages, data sources, and data source rows.",
            iconPath="/static/services/notion.png",
            releaseStatus="alpha",
            featureFlag="dwh-notion",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="notion_integration_id",
                        label="Notion workspace",
                        required=True,
                        kind="notion",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Notion credentials. Please reconnect your Notion workspace.",
            "403 Client Error": "Notion access forbidden. The integration may have been removed or its permissions revoked.",
        }

    def _get_access_token(self, config: NotionSourceConfig, team_id: int) -> str:
        integration = self.get_oauth_integration(config.notion_integration_id, team_id)

        # Notion tokens currently don't expire and don't issue refresh_token, so
        # access_token_expired() returns False and refresh is a no-op. We still go
        # through OauthIntegration to keep the surface uniform with other OAuth sources.
        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()

        if not integration.access_token:
            raise ValueError("Notion access token not found")
        return integration.access_token

    def get_schemas(
        self,
        config: NotionSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        # Build only the schemas the caller actually asked for. Static endpoints get
        # filtered upfront via `names`; dynamic data source rows are fetched live below.
        schemas: list[SourceSchema] = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(NOTION_STATIC_ENDPOINTS[endpoint].incremental_fields),
                supports_append=bool(NOTION_STATIC_ENDPOINTS[endpoint].incremental_fields),
                incremental_fields=NOTION_STATIC_ENDPOINTS[endpoint].incremental_fields,
            )
            for endpoint in STATIC_ENDPOINTS
            if names is None or endpoint in names
        ]

        # Data source row tables are discovered live — one warehouse table per Notion data
        # source (each Notion database hosts one or more data sources). Let API failures
        # propagate so the user sees the real error (revoked token, missing scope, Notion
        # outage) instead of silently getting back only the static schemas.
        #
        # Three discovery modes, depending on what the caller asked for:
        #   - `names is None`:                full enumeration via /v1/search
        #   - `names` has dynamic schemas:    per-id GET /v1/data_sources/{id}
        #   - `names` is static-only:         skip the Notion API entirely
        ids_to_fetch: list[str] | None = None
        skip_discovery = False
        if names is not None:
            dynamic_ids = [n[len(DATA_SOURCE_ROWS_PREFIX) :] for n in names if n.startswith(DATA_SOURCE_ROWS_PREFIX)]
            if dynamic_ids:
                ids_to_fetch = dynamic_ids
            else:
                skip_discovery = True

        if not skip_discovery:
            access_token = self._get_access_token(config, team_id)
            for data_source_id, title in _list_data_sources(access_token, ids=ids_to_fetch):
                schemas.append(
                    SourceSchema(
                        name=data_source_rows_schema_name(data_source_id),
                        label=title or "Untitled data source",
                        supports_incremental=True,
                        supports_append=True,
                        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
                    )
                )

        return schemas

    def validate_credentials(
        self, config: NotionSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._get_access_token(config, team_id)
            return validate_notion_credentials(access_token)
        except Exception as e:
            return False, str(e)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NotionResumeConfig]:
        return ResumableSourceManager[NotionResumeConfig](inputs, NotionResumeConfig)

    def source_for_pipeline(
        self,
        config: NotionSourceConfig,
        resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        access_token = self._get_access_token(config, inputs.team_id)

        return notion_source(
            access_token=access_token,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
        )
