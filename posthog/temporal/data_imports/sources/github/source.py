from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.models.integration import GitHubIntegration, Integration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common import config
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import GithubSourceConfig
from posthog.temporal.data_imports.sources.github.github import (
    github_source,
    validate_credentials as validate_github_credentials,
)
from posthog.temporal.data_imports.sources.github.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@config.config
class GithubSourcePATConfig(config.Config):
    """Legacy config for PAT-based authentication (backward compatibility only)"""

    personal_access_token: str
    repository: str


@SourceRegistry.register
class GithubSource(SimpleSource[GithubSourceConfig | GithubSourcePATConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GITHUB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GITHUB,
            label="GitHub",
            betaSource=True,
            caption="Select an existing GitHub account to link to PostHog or create a new connection",
            iconPath="/static/services/github.png",
            iconClassName="dark:bg-white rounded",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="github_integration_id",
                        label="GitHub account",
                        required=True,
                        kind="github",
                    ),
                    SourceFieldInputConfig(
                        name="repository",
                        label="Repository",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="owner/repo",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid GitHub credentials. Please reconnect your account.",
            "403 Client Error": "Access forbidden. Your token may lack required permissions or have hit rate limits.",
            "404 Client Error": "Repository not found. Please verify the repository name and access permissions.",
            "Bad credentials": "Your GitHub connection is invalid or expired. Please reconnect.",
        }

    def _get_github_integration(self, integration_id: int, team_id: int) -> Integration:
        """Get GitHub integration and refresh token if needed"""
        if not integration_id:
            raise ValueError("Missing GitHub integration ID")

        integration = Integration.objects.filter(id=integration_id, team_id=team_id, kind="github").first()
        if not integration:
            raise ValueError(f"GitHub integration not found: {integration_id}")

        # Refresh token if expired
        github_integration = GitHubIntegration(integration)
        if github_integration.access_token_expired():
            github_integration.refresh_access_token()

        return integration

    def parse_config(self, job_inputs: dict) -> GithubSourceConfig | GithubSourcePATConfig:
        if "personal_access_token" in job_inputs and "github_integration_id" not in job_inputs:
            return GithubSourcePATConfig.from_dict(job_inputs)
        return GithubSourceConfig.from_dict(job_inputs)

    def get_schemas(
        self, config: GithubSourceConfig | GithubSourcePATConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(
        self, config: GithubSourceConfig | GithubSourcePATConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Handle legacy PAT config (backward compatibility)
        if isinstance(config, GithubSourcePATConfig):
            return validate_github_credentials(config.personal_access_token, config.repository)

        # GitHub App integration path
        try:
            integration = self._get_github_integration(config.github_integration_id, team_id)
            if not integration.access_token:
                return False, "GitHub access token not found"
            return validate_github_credentials(integration.access_token, config.repository)
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(
        self, config: GithubSourceConfig | GithubSourcePATConfig, inputs: SourceInputs
    ) -> SourceResponse:
        # Handle legacy PAT config (backward compatibility)
        if isinstance(config, GithubSourcePATConfig):
            access_token = config.personal_access_token
        else:
            # GitHub App integration path
            integration = self._get_github_integration(config.github_integration_id, inputs.team_id)
            if not integration.access_token:
                raise ValueError(f"GitHub access token not found for job {inputs.job_id}")
            access_token = integration.access_token

        return github_source(
            personal_access_token=access_token,
            repository=config.repository,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
