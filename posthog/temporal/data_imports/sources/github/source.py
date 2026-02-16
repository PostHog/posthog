from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

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
            caption="""Enter your GitHub personal access token and repository to pull data into the PostHog Data warehouse.

You can create a personal access token in your [GitHub Settings](https://github.com/settings/tokens) under **Developer settings > Personal access tokens**.

The token needs `repo` scope for private repositories, or just `public_repo` for public repositories.
""",
            iconPath="/static/services/github.png",
            iconClassName="dark:bg-white rounded",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="github_pat_...",
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
            "401 Client Error": "Invalid GitHub personal access token. Please check your token and try again.",
            "403 Client Error": "Access forbidden. Your token may lack required permissions or have hit rate limits. Please check your token permissions.",
            "404 Client Error": "Repository not found. Please verify the repository name and that your token has access to it.",
        }

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
        return validate_github_credentials(config.personal_access_token, config.repository)

    def source_for_pipeline(self, config: GithubSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return github_source(
            personal_access_token=config.personal_access_token,
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
