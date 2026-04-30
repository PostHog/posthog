from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from requests import Request, Response
from requests.exceptions import RequestException

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resource
from posthog.temporal.data_imports.sources.common.rest_source.fanout import build_dependent_resource
from posthog.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from posthog.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from posthog.temporal.data_imports.sources.typeform.settings import (
    ALLOWED_TYPEFORM_API_BASE_URLS,
    DEFAULT_TYPEFORM_API_BASE_URL,
    TYPEFORM_ENDPOINTS,
    TypeformEndpointConfig,
)


def _normalize_api_base_url(api_base_url: str | None) -> str:
    return (api_base_url or DEFAULT_TYPEFORM_API_BASE_URL).rstrip("/")


def _validated_api_base_url(api_base_url: str | None) -> str:
    normalized_url = _normalize_api_base_url(api_base_url)
    if normalized_url not in ALLOWED_TYPEFORM_API_BASE_URLS:
        raise ValueError(
            "API base URL must be one of https://api.typeform.com, https://api.eu.typeform.com, or https://api.typeform.eu."
        )
    return normalized_url


def _coerce_datetime_to_utc(value: Any) -> datetime | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _start_param_for_typeform(value: Any) -> str:
    normalized_value = _coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)

    capped = min(normalized_value, datetime.now(UTC))
    return capped.strftime("%Y-%m-%dT%H:%M:%SZ")


def _typeform_incremental_window(cursor_path: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": "since",
        "end_param": "until",
        "initial_value": "1970-01-01T00:00:00Z",
        "end_value": _start_param_for_typeform(datetime.now(UTC)),
        "convert": _start_param_for_typeform,
    }


def _auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}", "Accept": "application/json"}


def _rest_api_client_config(base_api_url: str, auth_token: str) -> ClientConfig:
    return {
        "base_url": base_api_url,
        "auth": {"type": "bearer", "token": auth_token},
        "headers": {"Accept": "application/json"},
    }


class TypeformFormsPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._current_page = 1
        self._total_pages = 1

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        payload = response.json()
        page_count = payload.get("page_count", 1) if isinstance(payload, dict) else 1
        self._total_pages = page_count if isinstance(page_count, int) and page_count > 0 else 1
        self._has_next_page = self._current_page < self._total_pages

    def update_request(self, request: Request) -> None:
        self._current_page += 1
        if request.params is None:
            request.params = {}
        request.params["page"] = self._current_page


class TypeformResponsesPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._cursor: str | None = None

    def init_request(self, request: Request) -> None:
        self._cursor = None
        self._has_next_page = True

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if not data:
            self._cursor = None
            self._has_next_page = False
            return

        last_item = data[-1]
        if isinstance(last_item, dict):
            cursor = last_item.get("token")
            self._cursor = cursor if isinstance(cursor, str) and cursor else None
        else:
            self._cursor = None
        self._has_next_page = self._cursor is not None

    def update_request(self, request: Request) -> None:
        if self._cursor:
            if request.params is None:
                request.params = {}
            # Typeform rejects mixing token cursor pagination with datetime window filters.
            # Keep since/until only on the first request, then continue with before token.
            request.params.pop("since", None)
            request.params.pop("until", None)
            request.params["before"] = self._cursor


def validate_credentials(
    auth_token: str, api_base_url: str | None = None, schema_name: str | None = None
) -> tuple[bool, str | None]:
    try:
        base_url = _validated_api_base_url(api_base_url)
    except ValueError as exc:
        return False, str(exc)

    headers = _auth_headers(auth_token)
    errors: list[str] = []

    skip_responses_validation = False
    if schema_name == "forms":
        skip_responses_validation = True

    def _parse_error_description(response: Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                description = payload.get("description")
                if isinstance(description, str) and description:
                    return description
        except Exception:
            pass
        return response.text

    forms_response: Response | None = None
    try:
        forms_response = make_tracked_session().get(
            f"{base_url}/forms",
            headers=headers,
            params={"page_size": 1, "page": 1},
            timeout=10,
        )
        if forms_response.status_code == 401:
            errors.append("Invalid Typeform personal access token")
        elif forms_response.status_code == 403:
            errors.append("Typeform token is missing required scope for forms endpoint: forms:read")
        elif forms_response.status_code != 200:
            errors.append(f"/forms endpoint failed: {_parse_error_description(forms_response)}")

    except RequestException as exc:
        errors.append(f"/forms request failed: {exc}")

    if not skip_responses_validation and forms_response and forms_response.status_code == 200:
        forms_items = forms_response.json().get("items", [])

        # If there are no forms, we cannot probe /responses. This should not block validation.
        if forms_items:
            first_form = forms_items[0]
            form_id = first_form.get("id") if isinstance(first_form, dict) else None
            if not isinstance(form_id, str) or not form_id:
                errors.append("Typeform returned an invalid form id while validating responses access.")
            else:
                try:
                    responses_response = make_tracked_session().get(
                        f"{base_url}/forms/{form_id}/responses",
                        headers=headers,
                        params={"page_size": 1},
                        timeout=10,
                    )
                    if responses_response.status_code == 401:
                        errors.append("Invalid Typeform personal access token")
                    elif responses_response.status_code == 403:
                        errors.append("Typeform token is missing required scope for responses endpoint: responses:read")
                    elif responses_response.status_code != 200:
                        errors.append(f"/responses endpoint failed: {_parse_error_description(responses_response)}")
                except RequestException as exc:
                    errors.append(f"/responses request failed: {exc}")

    if errors:
        return False, "; ".join(errors)
    return True, None


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = TYPEFORM_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    params: dict[str, Any] = {
        "page_size": config.page_size,
        "page": 1,
        "sort_by": "last_updated_at",
        "order_by": "asc",
    }
    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
        "paginator": TypeformFormsPaginator(),
        "data_selector": "items",
    }
    if should_use_incremental_field and config.incremental_fields:
        endpoint_config["incremental"] = _typeform_incremental_window(
            incremental_field or config.default_incremental_field or "last_updated_at"
        )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field and config.incremental_fields
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(endpoint_config: TypeformEndpointConfig, items_fn) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def typeform_source(
    auth_token: str,
    api_base_url: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = TYPEFORM_ENDPOINTS[endpoint]
    base_api_url = _validated_api_base_url(api_base_url)

    if endpoint_config.fanout:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=TYPEFORM_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_rest_api_client_config(base_api_url, auth_token),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_typeform_incremental_window,
                page_size_param="page_size",
                parent_endpoint_extra={
                    "paginator": TypeformFormsPaginator(),
                    "data_selector": "items",
                },
                child_endpoint_extra={
                    "paginator": TypeformResponsesPaginator(),
                    "data_selector": "items",
                },
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _rest_api_client_config(base_api_url, auth_token),
        "resource_defaults": {
            "write_disposition": "replace",
            "endpoint": {"params": {"page_size": endpoint_config.page_size, "page": 1}},
        },
        "resources": [
            get_resource(
                endpoint=endpoint,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
            )
        ],
    }

    resource = rest_api_resource(config, team_id, job_id, db_incremental_field_last_value)
    return _make_source_response(endpoint_config, lambda: resource)
