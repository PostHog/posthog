from typing import Optional, cast

import requests

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import GoogleSearchConsoleSourceConfig
from posthog.temporal.data_imports.sources.google_search_console.google_search_console import (
    GoogleSearchConsoleResumeConfig,
    google_search_console_session,
    google_search_console_source,
    list_sites,
)
from posthog.temporal.data_imports.sources.google_search_console.settings import (
    SEARCH_ANALYTICS_INCREMENTAL_FIELD,
    SEARCH_ANALYTICS_SCHEMAS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleSearchConsoleSource(
    ResumableSource[GoogleSearchConsoleSourceConfig, GoogleSearchConsoleResumeConfig], OAuthMixin
):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLESEARCHCONSOLE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Google Search Console connection is invalid or expired. Please reconnect your account.",
            "403 Client Error": "PostHog is not authorized to read this Search Console property. Please make sure the connected Google account has access to the property.",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "Insufficient permissions. Please reconnect your Google Search Console account with the required scopes.",
        }

    def get_schemas(
        self,
        config: GoogleSearchConsoleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=[SEARCH_ANALYTICS_INCREMENTAL_FIELD],
                description=schema["description"],
                should_sync_default=schema["should_sync_default"],
            )
            for name, schema in SEARCH_ANALYTICS_SCHEMAS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[GoogleSearchConsoleResumeConfig]:
        return ResumableSourceManager[GoogleSearchConsoleResumeConfig](inputs, GoogleSearchConsoleResumeConfig)

    def source_for_pipeline(
        self,
        config: GoogleSearchConsoleSourceConfig,
        resumable_source_manager: ResumableSourceManager[GoogleSearchConsoleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return google_search_console_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    def validate_credentials(
        self,
        config: GoogleSearchConsoleSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        try:
            session = google_search_console_session(config.google_search_console_integration_id, team_id)
        except Exception as e:
            return False, f"Could not load Google Search Console credentials: {e}"

        try:
            sites = list_sites(session)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                return (
                    False,
                    "Google Search Console rejected the credentials. Please reconnect your account and ensure it has read access to the property.",
                )
            return False, f"Failed to list Google Search Console sites: {e}"
        except Exception as e:
            return False, f"Failed to list Google Search Console sites: {e}"

        normalized = {site.get("siteUrl"): site.get("permissionLevel") for site in sites}
        site_url = config.site_url
        if site_url not in normalized:
            return (
                False,
                f"Site '{site_url}' is not visible to the connected Google account. Verify the property URL "
                f"(e.g. 'https://example.com/' or 'sc-domain:example.com') and that the account has access.",
            )
        permission = normalized[site_url]
        if permission == "siteUnverifiedUser":
            return (
                False,
                f"The connected Google account does not have verified access to '{site_url}'. "
                f"Verify the property in Search Console and try again.",
            )
        return True, None

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_SEARCH_CONSOLE,
            label="Google Search Console",
            caption=(
                "Connect a verified Google Search Console property to sync daily Search Analytics performance data "
                "(clicks, impressions, CTR, average position). Requires a Google account with read access to the property."
            ),
            unreleasedSource=True,
            releaseStatus="alpha",
            featureFlag="dwh-google-search-console",
            iconPath="/static/services/google-search-console.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/google-search-console",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="google_search_console_integration_id",
                        label="Google Search Console account",
                        required=True,
                        kind="google-search-console",
                    ),
                    SourceFieldInputConfig(
                        name="site_url",
                        label="Property URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://example.com/ or sc-domain:example.com",
                        caption=(
                            "The exact verified property URL as it appears in Google Search Console. "
                            "Use the trailing slash for URL prefix properties or the `sc-domain:` prefix for domain properties."
                        ),
                        secret=False,
                    ),
                ],
            ),
        )
