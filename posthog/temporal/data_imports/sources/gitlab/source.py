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
from posthog.temporal.data_imports.sources.generated_configs import GitlabSourceConfig
from posthog.temporal.data_imports.sources.gitlab.settings import (
    ENDPOINTS as GITLAB_ENDPOINTS,
    INCREMENTAL_FIELDS as GITLAB_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.sources.gitlab.gitlab import (
    GitLabPermissionError,
    GitLabAPIError,
    gitlab_source,
    validate_credentials as validate_gitlab_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GitlabSource(SimpleSource[GitlabSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GITLAB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GITLAB,
            caption="""Connect your GitLab account to automatically sync your GitLab data into PostHog Data warehouse.

You'll need a GitLab personal access token with **read_api** scope. You can create one in your [GitLab Access Tokens settings](https://gitlab.com/-/user_settings/personal_access_tokens).

**For self-hosted GitLab:** Enter your GitLab instance URL (e.g., `gitlab.company.com` or `https://gitlab.company.com`)

**For GitLab.com:** Leave the Base URL field empty or use `gitlab.com`

**Project ID:** Enter the project ID or path (e.g., `123456` or `group/project-name`). Leave empty to sync all accessible projects for global endpoints like users and groups.
""",
            iconPath="/static/services/gitlab.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/gitlab",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="glpat-xxxxxxxxxxxxxxxxxxxx",
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Base URL (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="gitlab.com (or your self-hosted instance)",
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID or path (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="123456 or group/project-name",
                    ),
                ],
            ),
            feature_flag="dwh_gitlab",
        )

    def get_schemas(self, config: GitlabSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=GITLAB_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=GITLAB_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in GITLAB_ENDPOINTS
        ]

    def validate_credentials(self, config: GitlabSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_gitlab_credentials(config.access_token, config.base_url):
                return True, None
            else:
                return False, "Invalid GitLab credentials"
        except GitLabPermissionError as e:
            return False, str(e)
        except GitLabAPIError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    def source_for_pipeline(self, config: GitlabSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return gitlab_source(
            access_token=config.access_token,
            base_url=config.base_url,
            project_id=config.project_id,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
        )
