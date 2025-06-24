import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode

import dlt
import structlog
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.common.logger import get_temporal_context
from posthog.temporal.data_imports.pipelines.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.pipelines.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.pipelines.salesforce.auth import SalesforceAuth

LOGGER = structlog.get_logger()


# Note: When pulling all fields, salesforce requires a 200 limit. We circumvent the pagination by using Id ordering.
def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "User": {
            "name": "User",
            "table_name": "user",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM User WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM User ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "UserRole": {
            "name": "UserRole",
            "table_name": "user_role",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM UserRole WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM UserRole ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Lead": {
            "name": "Lead",
            "table_name": "lead",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Lead WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Lead ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Contact": {
            "name": "Contact",
            "table_name": "contact",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Contact WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Contact ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Campaign": {
            "name": "Campaign",
            "table_name": "campaign",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Campaign WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Campaign ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Product2": {
            "name": "Product2",
            "table_name": "product2",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Product2 WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Product2 ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Pricebook2": {
            "name": "Pricebook2",
            "table_name": "pricebook2",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Pricebook2 WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Pricebook2 ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "PricebookEntry": {
            "name": "PricebookEntry",
            "table_name": "pricebook_entry",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM PricebookEntry WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM PricebookEntry ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Order": {
            "name": "Order",
            "table_name": "order",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Order WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Order ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Opportunity": {
            "name": "Opportunity",
            "table_name": "opportunity",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Opportunity WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Opportunity ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Account": {
            "name": "Account",
            "table_name": "account",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Account WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Account ORDER BY Id ASC LIMIT 200",
                },
                "response_actions": [],
            },
            "table_format": "delta",
        },
        "Event": {
            "name": "Event",
            "table_name": "event",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Event WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Event ORDER BY Id ASC LIMIT 200",
                },
                "response_actions": [],
            },
            "table_format": "delta",
        },
        "Task": {
            "name": "Task",
            "table_name": "task",
            "primary_key": "Id" if should_use_incremental_field else None,
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
            "endpoint": {
                "data_selector": "records",
                "path": "/services/data/v61.0/query",
                "params": {
                    "q": {
                        "type": "incremental",
                        "cursor_path": "SystemModstamp",
                        "initial_value": "2000-01-01T00:00:00.000+0000",
                        "convert": lambda date_str: f"SELECT FIELDS(ALL) FROM Task WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200",
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Task ORDER BY Id ASC LIMIT 200",
                },
                "response_actions": [],
            },
            "table_format": "delta",
        },
    }

    return resources[name]


class SalesforceEndpointPaginator(BasePaginator):
    def __init__(self, instance_url, should_use_incremental_field: bool):
        super().__init__()
        self.instance_url = instance_url
        self.should_use_incremental_field = should_use_incremental_field

    def __repr__(self):
        pairs = (
            f"{attr}={repr(getattr(self, attr))}"
            for attr in ("should_use_incremental_field", "_has_next_page", "_model_name", "_last_record_id")
        )
        return f"<SalesforceEndpointPaginator at {hex(id(self))}: {', '.join(pairs)}>"

    @property
    def logger(self):
        temporal_context = get_temporal_context()
        return LOGGER.bind(**temporal_context)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        if not res or not res["records"]:
            self._has_next_page = False
            self.logger.debug(
                "No more Salesforce pages",
                instance_url=self.instance_url,
                should_use_incremental_field=self.should_use_incremental_field,
            )
            return

        last_record = res["records"][-1]
        model_name = res["records"][0]["attributes"]["type"]

        self.logger.debug(
            "More Salesforce pages required",
            instance_url=self.instance_url,
            should_use_incremental_field=self.should_use_incremental_field,
            model_name=model_name,
            last_record_id=last_record["Id"],
        )

        self._has_next_page = True
        self._last_record_id = last_record["Id"]
        self._model_name = model_name

    def update_request(self, request: Request) -> None:
        if not self._has_next_page:
            return

        if self.should_use_incremental_field:
            # Cludge: Need to get initial value for date filter
            query = request.params.get("q", "")
            date_match = re.search(r"SystemModstamp >= (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.+?)\s", query)

            self.logger.debug(
                "Constructing incremental query",
                instance_url=self.instance_url,
                should_use_incremental_field=self.should_use_incremental_field,
                model_name=self._model_name,
                last_record_id=self._last_record_id,
            )

            if date_match:
                date_filter = date_match.group(1)
                query = f"SELECT FIELDS(ALL) FROM {self._model_name} WHERE Id > '{self._last_record_id}' AND SystemModstamp >= {date_filter} ORDER BY Id ASC LIMIT 200"
            else:
                raise ValueError("No date filter found in initial query. Incremental loading requires a date filter.")
        else:
            self.logger.debug(
                "Constructing non-incremental query",
                instance_url=self.instance_url,
                should_use_incremental_field=self.should_use_incremental_field,
                model_name=self._model_name,
                last_record_id=self._last_record_id,
            )

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
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": instance_url,
            "auth": SalesforceAuth(refresh_token, access_token, instance_url),
            "paginator": SalesforceEndpointPaginator(
                instance_url=instance_url, should_use_incremental_field=should_use_incremental_field
            ),
        },
        "resource_defaults": {
            "primary_key": "id" if should_use_incremental_field else None,
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    yield from rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
