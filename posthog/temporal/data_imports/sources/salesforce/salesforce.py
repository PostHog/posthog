import re
import dataclasses
from datetime import datetime
from typing import Any, Optional

from requests import Request, Response

from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.salesforce.auth import SalesforceAuth


@dataclasses.dataclass
class SalesforceResumeConfig:
    model_name: str
    last_record_id: str
    # Preserved from the initial SOQL query so the resumed run re-applies the same
    # `SystemModstamp >= ...` predicate; None for non-incremental (full-refresh) runs.
    date_filter: Optional[str] = None


# Note: When pulling all fields, salesforce requires a 200 limit. We circumvent the pagination by using Id ordering.
def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "User": {
            "name": "User",
            "table_name": "user",
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM User WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM UserRole WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Lead WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Contact WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Campaign WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Product2 WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Pricebook2 WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM PricebookEntry WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Order WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Opportunity WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM Opportunity ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "OpportunityHistory": {
            "name": "OpportunityHistory",
            "table_name": "opportunity_history",
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM OpportunityHistory WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
                    }
                    if should_use_incremental_field
                    else "SELECT FIELDS(ALL) FROM OpportunityHistory ORDER BY Id ASC LIMIT 200",
                },
            },
            "table_format": "delta",
        },
        "Account": {
            "name": "Account",
            "table_name": "account",
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Account WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Event WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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
                        "convert": lambda date_str: (
                            f"SELECT FIELDS(ALL) FROM Task WHERE SystemModstamp >= {date_str.isoformat() if isinstance(date_str, datetime) else date_str} ORDER BY Id ASC LIMIT 200"
                        ),
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


_DATE_FILTER_RE = re.compile(r"SystemModstamp >= (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.+?)\s")


def _build_next_query(model_name: str, last_record_id: str, date_filter: Optional[str]) -> str:
    if date_filter is not None:
        return (
            f"SELECT FIELDS(ALL) FROM {model_name} "
            f"WHERE Id > '{last_record_id}' AND SystemModstamp >= {date_filter} "
            f"ORDER BY Id ASC LIMIT 200"
        )
    return f"SELECT FIELDS(ALL) FROM {model_name} WHERE Id > '{last_record_id}' ORDER BY Id ASC LIMIT 200"


class SalesforceEndpointPaginator(BasePaginator):
    def __init__(self, should_use_incremental_field: bool):
        super().__init__()
        self.should_use_incremental_field = should_use_incremental_field
        self._model_name: Optional[str] = None
        self._last_record_id: Optional[str] = None
        self._date_filter: Optional[str] = None

    def __repr__(self) -> str:
        pairs = (
            f"{attr}={repr(getattr(self, attr))}"
            for attr in ("should_use_incremental_field", "_has_next_page", "_model_name", "_last_record_id")
        )
        return f"<SalesforceEndpointPaginator at {hex(id(self))}: {', '.join(pairs)}>"

    def init_request(self, request: Request) -> None:
        # When seeded via set_resume_state, skip the initial request and jump directly
        # to the next page after the saved checkpoint.
        if self._has_next_page and self._model_name and self._last_record_id:
            self._advance_query(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        res = response.json()

        if not res or not res["records"]:
            self._has_next_page = False
            return

        last_record = res["records"][-1]
        model_name = res["records"][0]["attributes"]["type"]

        self._has_next_page = True
        self._last_record_id = last_record["Id"]
        self._model_name = model_name

    def update_request(self, request: Request) -> None:
        if not self._has_next_page:
            return

        if self.should_use_incremental_field:
            # Pull the initial-query date filter once, then cache it on the paginator so
            # resume can restore it without re-parsing the original request.
            if self._date_filter is None:
                query = (request.params or {}).get("q", "")
                date_match = _DATE_FILTER_RE.search(query)

                if not date_match:
                    raise ValueError(
                        "No date filter found in initial query. Incremental loading requires a date filter."
                    )

                self._date_filter = date_match.group(1)

        self._advance_query(request)

    def _advance_query(self, request: Request) -> None:
        # Mutate ``request.params["q"]`` rather than ``request.url`` so ``requests`` does
        # not end up merging the old and new query strings into duplicate ``q`` params
        # when it prepares the next request.
        if self._model_name is None or self._last_record_id is None:
            raise ValueError("Cannot advance paginator: model_name or last_record_id is not set")
        if self.should_use_incremental_field and self._date_filter is None:
            # Guards against stale/corrupted resume state that omits the date filter —
            # without it we would silently drop the SystemModstamp predicate and
            # over-fetch records.
            raise ValueError("Cannot advance paginator: date_filter is required for incremental mode")
        date_filter = self._date_filter if self.should_use_incremental_field else None
        if request.params is None:
            request.params = {}
        request.params["q"] = _build_next_query(self._model_name, self._last_record_id, date_filter)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not (self._has_next_page and self._model_name and self._last_record_id):
            return None
        if self.should_use_incremental_field and self._date_filter is None:
            return None
        state: dict[str, Any] = {
            "model_name": self._model_name,
            "last_record_id": self._last_record_id,
        }
        if self._date_filter is not None:
            state["date_filter"] = self._date_filter
        return state

    def set_resume_state(self, state: dict[str, Any]) -> None:
        model_name = state.get("model_name")
        last_record_id = state.get("last_record_id")
        if not model_name or not last_record_id:
            return
        self._model_name = model_name
        self._last_record_id = last_record_id
        self._date_filter = state.get("date_filter")
        self._has_next_page = True


def salesforce_source(
    instance_url: str,
    access_token: str,
    refresh_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    resumable_source_manager: ResumableSourceManager[SalesforceResumeConfig],
    should_use_incremental_field: bool = False,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": instance_url,
            "auth": SalesforceAuth(refresh_token, access_token, instance_url),
            "paginator": SalesforceEndpointPaginator(should_use_incremental_field=should_use_incremental_field),
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = dataclasses.asdict(resume_config)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("model_name") and state.get("last_record_id"):
            resumable_source_manager.save_state(SalesforceResumeConfig(**state))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
