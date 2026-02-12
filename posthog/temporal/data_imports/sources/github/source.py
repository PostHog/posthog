from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    Option,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
)

from posthog.models.integration import GitHubIntegration, Integration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
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


@SourceRegistry.register
class GithubSource(SimpleSource[GithubSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GITHUB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GITHUB,
            label="GitHub",
            betaSource=True,
            caption="Connect your GitHub repository to sync issues, pull requests, commits, and more.",
            iconPath="/static/services/github.png",
            iconClassName="dark:bg-white rounded",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="oauth",
                        options=[
                            Option(
                                label="OAuth (GitHub App)",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="github_integration_id",
                                            label="GitHub account",
                                            required=False,
                                            kind="github",
                                        ),
                                    ],
                                ),
                            ),
                            Option(
                                label="Personal access token",
                                value="pat",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="personal_access_token",
                                            label="Personal access token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="github_pat_...",
                                        ),
                                    ],
                                ),
                            ),
                        ],
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

    def _get_access_token(self, config: GithubSourceConfig, team_id: int) -> str:
        if config.auth_method.selection == "pat":
            if not config.auth_method.personal_access_token:
                raise ValueError("Missing personal access token")
            return config.auth_method.personal_access_token

        if not config.auth_method.github_integration_id:
            raise ValueError("Missing GitHub integration ID")
        integration = self._get_github_integration(config.auth_method.github_integration_id, team_id)
        if not integration.access_token:
            raise ValueError("GitHub access token not found")
        return integration.access_token

    def get_schemas(self, config: GithubSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
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
        self, config: GithubSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._get_access_token(config, team_id)
            return validate_github_credentials(access_token, config.repository)
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: GithubSourceConfig, inputs: SourceInputs) -> SourceResponse:
        access_token = self._get_access_token(config, inputs.team_id)

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
