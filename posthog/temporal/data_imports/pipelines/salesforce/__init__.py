import dlt
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.requests import Response, Request
from posthog.temporal.data_imports.pipelines.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource
from posthog.warehouse.models.external_table_definitions import get_dlt_mapping_for_external_table


def get_resource(name: str, is_incremental: bool) -> EndpointResource:
    resources = dict[str, EndpointResource] = {}

    return resources[name]


@dlt.source(max_table_nesting=0)
def salesforce_source(
    subdomain: str, api_key: str, endpoint: str, team_id: int, job_id: str, is_incremental: bool = False
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{subdomain}.my.salesforce.com/services/data/v61.0",
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
        },
        "resource_defaults": {
            "primary_key": "id",
        },
        "resources": [get_resource(endpoint, is_incremental)],
    }

    yield from rest_api_resources(config, team_id, job_id)
