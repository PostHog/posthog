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
from posthog.temporal.data_imports.sources.generated_configs import JiraSourceConfig
from posthog.temporal.data_imports.sources.jira.helpers import JiraAPIError, JiraClient, validate_credentials
from posthog.temporal.data_imports.sources.jira.settings import (
    ENDPOINTS as JIRA_ENDPOINTS,
    INCREMENTAL_FIELDS as JIRA_INCREMENTAL_FIELDS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JiraSource(SimpleSource[JiraSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JIRA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JIRA,
            caption="""Enter your Jira credentials to automatically pull your Jira data into the PostHog Data warehouse.

You'll need:
- Your Jira domain (e.g., your-company.atlassian.net)
- Your email address associated with your Jira account
- An API token which you can create at [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens)

The API token requires the following permissions:
- Read access to projects, issues, and users
- Read access to boards and sprints (for Jira Software)
""",
            iconPath="/static/services/jira.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/jira",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="jira_domain",
                        label="Jira domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-company.atlassian.net",
                    ),
                    SourceFieldInputConfig(
                        name="jira_email",
                        label="Email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="user@example.com",
                    ),
                    SourceFieldInputConfig(
                        name="jira_api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Jira API token",
                    ),
                ],
            ),
            feature_flag="dwh_jira",
        )

    def validate_credentials(self, config: JiraSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            from posthog.temporal.common.logger import PipelineLogger

            logger = PipelineLogger(0, "validate_credentials", "jira")

            if validate_credentials(config.jira_domain, config.jira_email, config.jira_api_token, logger):
                return True, None
            else:
                return False, "Invalid Jira credentials"
        except JiraAPIError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Error validating credentials: {str(e)}"

    def get_schemas(self, config: JiraSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=JIRA_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=JIRA_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in JIRA_ENDPOINTS
        ]

    def source_for_pipeline(self, config: JiraSourceConfig, inputs: SourceInputs) -> SourceResponse:
        client = JiraClient(config.jira_domain, config.jira_email, config.jira_api_token, inputs.logger)

        endpoint = inputs.schema_name
        incremental_value = inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None

        # Get the appropriate data based on the endpoint
        if endpoint == "issues":
            items = client.get_issues(incremental_value=incremental_value)
            primary_keys = ["id"]
            partition_keys = ["fields.created"]
            partition_format = "YYYY-MM"
        elif endpoint == "projects":
            items = client.get_projects()
            primary_keys = ["id"]
            partition_keys = None
            partition_format = None
        elif endpoint == "users":
            items = client.get_users()
            primary_keys = ["accountId"]
            partition_keys = None
            partition_format = None
        elif endpoint == "issue_comments":
            items = client.get_issue_comments(incremental_value=incremental_value)
            primary_keys = ["id"]
            partition_keys = ["created"]
            partition_format = "YYYY-MM"
        elif endpoint == "boards":
            items = client.get_boards()
            primary_keys = ["id"]
            partition_keys = None
            partition_format = None
        elif endpoint == "sprints":
            items = client.get_sprints()
            primary_keys = ["id"]
            partition_keys = ["startDate"]
            partition_format = "YYYY-MM"
        elif endpoint == "components":
            items = client.get_components()
            primary_keys = ["id"]
            partition_keys = None
            partition_format = None
        elif endpoint == "worklogs":
            items = client.get_worklogs(incremental_value=incremental_value)
            primary_keys = ["id"]
            partition_keys = ["created"]
            partition_format = "YYYY-MM"
        else:
            raise ValueError(f"Unsupported endpoint: {endpoint}")

        return SourceResponse(
            items=items,
            primary_keys=primary_keys,
            partition_keys=partition_keys,
            partition_mode="datetime" if partition_keys else None,
            partition_format=partition_format,
        )
