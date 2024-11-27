from typing import Any, Optional
import dlt
from urllib.parse import urlencode
from dlt.sources.helpers.rest_client.paginators import BasePaginator
from dlt.sources.helpers.requests import Response, Request
from posthog.temporal.data_imports.pipelines.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.pipelines.salesforce.auth import SalseforceAuth
import pendulum
import re


# Note: When pulling all fields, salesforce requires a 200 limit. We circumvent the pagination by using Id ordering.
def get_resource(name: str, is_incremental: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "User": {
            "name": "User",
            "table_name": "user",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM User WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM User ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "UserRole": {
            "name": "UserRole",
            "table_name": "user_role",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM UserRole WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM UserRole ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Lead": {
            "name": "Lead",
            "table_name": "lead",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Lead WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM Lead ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Contact": {
            "name": "Contact",
            "table_name": "contact",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Contact WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM Contact ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Campaign": {
            "name": "Campaign",
            "table_name": "campaign",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Campaign WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM Campaign ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Product2": {
            "name": "Product2",
            "table_name": "product2",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Product2 WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM Product2 ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Pricebook2": {
            "name": "Pricebook2",
            "table_name": "pricebook2",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Pricebook2 WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM Pricebook2 ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "PricebookEntry": {
            "name": "PricebookEntry",
            "table_name": "pricebook_entry",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM PricebookEntry WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM PricebookEntry ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Order": {
            "name": "Order",
            "table_name": "order",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Order WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM Order ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Opportunity": {
            "name": "Opportunity",
            "table_name": "opportunity",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Opportunity WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM Opportunity ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Account": {
            "name": "Account",
            "table_name": "account",
            **({"primary_key": "Id"} if is_incremental else {}),
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
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Account WHERE SystemModstamp >= {date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if is_incremental
                    else "SELECT FIELDS(ALL) FROM Account ORDER BY Id ASC LIMIT 200",
                },
                "response_actions": [],
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class SalesforceEndpointPaginator(BasePaginator):
    def __init__(self, instance_url, is_incremental: bool):
        super().__init__()
        self.instance_url = instance_url
        self.is_incremental = is_incremental

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        self._next_page = None

        if not res or not res["records"]:
            self._has_next_page = False
            return

        last_record = res["records"][-1]
        model_name = res["records"][0]["attributes"]["type"]

        self._has_next_page = True
        self._last_record_id = last_record["Id"]
        self._model_name = model_name

    def update_request(self, request: Request) -> None:
        if self.is_incremental:
            # Cludge: Need to get initial value for date filter
            query = request.params.get("q", "")
            date_match = re.search(r"SystemModstamp >= (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+\d{4})", query)
            if date_match:
                date_filter = date_match.group(1)
                query = f"SELECT FIELDS(ALL) FROM {self._model_name} WHERE Id > '{self._last_record_id}' AND SystemModstamp >= {date_filter} ORDER BY Id ASC LIMIT 200"
            else:
                raise ValueError("No date filter found in initial query. Incremental loading requires a date filter.")
        else:
            query = f"SELECT FIELDS(ALL) FROM {self._model_name} WHERE Id > '{self._last_record_id}' ORDER BY Id ASC LIMIT 200"

        _next_page = f"/services/data/v61.0/query" + "?" + urlencode({"q": query})
        request.url = f"{self.instance_url}{_next_page}"


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
            "paginator": SalesforceEndpointPaginator(instance_url=instance_url, is_incremental=is_incremental),
        },
        "resource_defaults": {
            **({"primary_key": "id"} if is_incremental else {}),
        },
        "resources": [get_resource(endpoint, is_incremental)],
    }

    yield from rest_api_resources(config, team_id, job_id)
