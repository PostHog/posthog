import dlt
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.requests import Response, Request
from posthog.temporal.data_imports.pipelines.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource
from posthog.warehouse.models.external_table_definitions import get_dlt_mapping_for_external_table


def get_resource(name: str, is_incremental: bool, subdomain: str) -> EndpointResource:
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
        },
        "Account": {
            "name": "Account",
            "table_name": "account",
            "primary_key": "id",
            "write_disposition": "merge" if is_incremental else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "paginator": SalesforceIncrementalPaginator(schema="Account", subdomain=subdomain),
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "SELECT FIELDS(STANDARD) FROM Account WHERE SystemModstamp > 2000-01-01T00:00:00.000+0000",
                    }
                    if is_incremental
                    else "SELECT FIELDS(STANDARD) FROM Account",
                },
            },
        },
    }

    return resources[name]


class SalesforceIncrementalPaginator(BasePaginator):
    def __init__(self, subdomain, schema):
        super().__init__()
        self.subdomain = subdomain
        self.schema = schema

    def update_state(self, response: Response) -> None:
        res = response.json()

        self._next_start_time = None
        self._next_page = None

        if not res:
            self._has_next_page = False
            return

        if not res["done"]:
            self._has_next_page = True
            self._next_page = res["nextRecordsUrl"]

            last_value_in_response = res["records"][-1]["SystemModstamp"]
            self._next_start_time = last_value_in_response
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}

        request.params["q"] = (
            f"SELECT FIELDS(STANDARD) FROM {self.schema} WHERE SystemModstamp > {self._next_start_time}"
        )

        request.url = f"https://{self.subdomain}.my.salesforce.com{self._next_page}"


class SalesforceEndpointPaginator(BasePaginator):
    def __init__(self, subdomain):
        super().__init__()
        self.subdomain = subdomain

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
        request.url = f"https://{self.subdomain}.my.salesforce.com{self._next_page}"


@dlt.source(max_table_nesting=0)
def salesforce_source(
    subdomain: str,
    access_token: str,
    refresh_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    is_incremental: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://{subdomain}.my.salesforce.com",
            "auth": {
                "type": "bearer",
                "token": access_token,
            },
            "paginator": SalesforceEndpointPaginator(subdomain=subdomain),
        },
        "resource_defaults": {
            "primary_key": "id",
        },
        "resources": [get_resource(endpoint, is_incremental, subdomain)],
    }

    yield from rest_api_resources(config, team_id, job_id)
