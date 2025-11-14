from typing import cast

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
    GitHubPermissionError,
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
            iconPath="/static/services/github.svg",
            iconClassName="dark:bg-white rounded",
            caption="""Enter your GitHub credentials to automatically pull your GitHub data into the PostHog data warehouse.

You'll need to provide a repository in the format `owner/repo` (e.g., `PostHog/posthog`) and a personal access token.

To create a personal access token:
1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a descriptive name and select the following scopes:
   - `repo` (Full control of private repositories) - for accessing repository data
   - `read:org` (Read org and team membership) - for organization data
   - `read:user` (Read user profile data) - for user data
4. Click "Generate token" and copy the token

**Note:** The token will only be shown once, so make sure to copy it immediately.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/github",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="github_repository",
                        label="Repository",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="owner/repo (e.g., PostHog/posthog)",
                    ),
                    SourceFieldInputConfig(
                        name="github_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="ghp_...",
                    ),
                ],
            ),
            featureFlag="dwh_github",
        )

    def validate_credentials(self, config: GithubSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_github_credentials(config.github_access_token, config.github_repository):
                return True, None
            return False, "Invalid GitHub credentials or repository not found"
        except GitHubPermissionError as e:
            missing_resources = ", ".join(e.missing_permissions.keys())
            return False, f"GitHub token lacks permissions for {missing_resources}"
        except Exception as e:
            return False, str(e)

    def get_schemas(self, config: GithubSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def source_for_pipeline(self, config: GithubSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return github_source(
            access_token=config.github_access_token,
            repository=config.github_repository,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
        )
