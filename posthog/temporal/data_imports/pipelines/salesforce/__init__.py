import dlt
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.requests import Response, Request
from posthog.temporal.data_imports.pipelines.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.pipelines.salesforce.auth import SalseforceAuth


def get_resource(name: str, is_incremental: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "User": {
            "name": "User",
            "table_name": "user",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": "SELECT FIELDS(STANDARD) FROM User",
                },
            },
            "table_format": "delta",
        },
        "UserRole": {
            "name": "UserRole",
            "table_name": "user_role",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": "SELECT FIELDS(STANDARD) FROM UserRole",
                },
            },
            "table_format": "delta",
        },
        "Lead": {
            "name": "Lead",
            "table_name": "lead",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": "SELECT FIELDS(STANDARD) FROM Lead",
                },
            },
            "table_format": "delta",
        },
        "Contact": {
            "name": "Contact",
            "table_name": "contact",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": "SELECT FIELDS(STANDARD) FROM Contact",
                },
            },
            "table_format": "delta",
        },
        "Campaign": {
            "name": "Campaign",
            "table_name": "campaign",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": "SELECT FIELDS(STANDARD) FROM Campaign",
                },
            },
            "table_format": "delta",
        },
        "Product2": {
            "name": "Product2",
            "table_name": "product2",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": "SELECT FIELDS(STANDARD) FROM Product2",
                },
            },
            "table_format": "delta",
        },
        "Pricebook2": {
            "name": "Pricebook2",
            "table_name": "pricebook2",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": "SELECT FIELDS(STANDARD) FROM Pricebook2",
                },
            },
            "table_format": "delta",
        },
        "PricebookEntry": {
            "name": "PricebookEntry",
            "table_name": "pricebook_entry",
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": "SELECT FIELDS(STANDARD) FROM PricebookEntry",
                },
            },
            "table_format": "delta",
        },
        "Account": {
            "name": "Account",
            "table_name": "account",
            "primary_key": "Id",
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(STANDARD) FROM Account WHERE SystemModstamp > {date_str}",
                    }
                    if is_incremental
                    else "SELECT FIELDS(STANDARD) FROM Account",
                },
                "response_actions": [],
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class SalesforceEndpointPaginator(BasePaginator):
    def __init__(self, instance_url):
        super().__init__()
        self.instance_url = instance_url

    def update_state(self, response: Response) -> None:
        res = response.json()

        self._next_page = None

        if not res:
            self._has_next_page = False
            return

        if not res["done"]:
            self._has_next_page = True
            self._next_page = res["nextRecordsUrl"]
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        request.url = f"{self.instance_url}{self._next_page}"


@dlt.source(max_table_nesting=0)
def salesforce_source(
    instance_url: str,
    access_token: str,
    refresh_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    is_incremental: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": instance_url,
            "auth": SalseforceAuth(refresh_token, access_token),
            "paginator": SalesforceEndpointPaginator(instance_url=instance_url),
        },
        "resource_defaults": {
            "primary_key": "id",
        },
        "resources": [get_resource(endpoint, is_incremental)],
    }

    yield from rest_api_resources(config, team_id, job_id)
