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
    GitHubAPIError,
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
            iconPath="/static/services/github.png",
            iconClassName="dark:bg-white rounded",
            caption="""Enter your GitHub credentials to automatically pull your GitHub data into the PostHog Data warehouse.

You can find your repository in the format `owner/repo` (e.g., `PostHog/posthog`).

To create a personal access token:
1. Go to GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Click "Generate new token"
3. Select the repositories you want to access
4. Grant the following permissions:
   - **Contents**: Read access (for commits, branches, tags)
   - **Issues**: Read access (for issues and issue comments)
   - **Pull requests**: Read access (for pull requests, reviews, and comments)
   - **Metadata**: Read access (automatically included)
   - **Actions**: Read access (for workflows and workflow runs)

You can also use a classic personal access token with the `repo` scope.
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
                        placeholder="owner/repo",
                    ),
                    SourceFieldInputConfig(
                        name="github_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="github_pat_...",
                    ),
                ],
            ),
            featureFlag="dwh_github",
        )

    def validate_credentials(self, config: GithubSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_github_credentials(config.github_access_token, config.github_repository):
                return True, None
            return False, "Invalid GitHub credentials"
        except GitHubPermissionError as e:
            missing_resources = ", ".join(e.missing_permissions.keys())
            return False, f"GitHub access token lacks permissions for {missing_resources}"
        except GitHubAPIError as e:
            return False, str(e)
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
