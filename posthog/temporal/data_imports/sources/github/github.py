import re
from datetime import date, datetime
from typing import Any, Optional

import requests
from dateutil import parser as dateutil_parser
from dlt.sources.helpers.requests import Request, Response
from dlt.sources.helpers.rest_client.paginators import BasePaginator

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.rest_source import RESTAPIConfig, rest_api_resources
from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.github.settings import GITHUB_ENDPOINTS


def _format_incremental_value(value: Any) -> str:
    """Format incremental field value as ISO string for GitHub API filters."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()).isoformat()
    return str(value)


def get_resource(
    name: str,
    repository: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = GITHUB_ENDPOINTS[name]

    # Build path with repository
    path = config.path.format(repository=repository)

    params: dict[str, Any] = {
        "per_page": config.page_size,
        "state": "all",  # Get all states for issues/PRs
    }

    # Handle incremental loading
    if should_use_incremental_field and db_incremental_field_last_value:
        formatted_value = _format_incremental_value(db_incremental_field_last_value)
        # Issues and commits support the 'since' parameter for incremental sync
        if name in ("issues", "commits"):
            params["since"] = formatted_value

    if should_use_incremental_field:
        sort_field = (incremental_field or config.default_incremental_field or "updated_at").replace("_at", "")
        params["sort"] = sort_field
        params["direction"] = config.sort_mode

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_key,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": path,
            "params": params,
        },
        "table_format": "delta",
    }


class GithubPaginator(BasePaginator):
    """Paginator for GitHub API using Link header pagination."""

    def __init__(
        self,
        incremental_field: str | None = None,
        db_incremental_field_last_value: datetime | None = None,
        sort_mode: str = "asc",
    ) -> None:
        super().__init__()
        self._next_url: str | None = None
        self._incremental_field = incremental_field
        self._db_incremental_field_last_value = db_incremental_field_last_value
        self._sort_mode = sort_mode

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        # GitHub uses Link header for pagination
        link_header = response.headers.get("Link", "")

        self._next_url = None
        self._has_next_page = False

        if link_header:
            # Parse Link header to find 'next' relation
            # Format: <url>; rel="next", <url>; rel="last"
            for part in link_header.split(","):
                part = part.strip()
                match = re.match(r'<([^>]+)>;\s*rel="next"', part)
                if match:
                    self._next_url = match.group(1)
                    self._has_next_page = True
                    break

        # For descending sort with incremental sync, stop pagination when we hit old records
        if (
            self._has_next_page
            and self._sort_mode == "desc"
            and self._incremental_field
            and self._db_incremental_field_last_value
            and data
        ):
            # Check if we've hit any item older than our cutoff
            # With desc sort, once we hit an old record, we can stop
            any_item_older = any(self._is_older_than_cutoff(item.get(self._incremental_field)) for item in data if item)
            if any_item_older:
                self._has_next_page = False
                self._next_url = None

    def _is_older_than_cutoff(self, value: str | datetime | None) -> bool:
        if value is None or self._db_incremental_field_last_value is None:
            return False

        if isinstance(value, str):
            try:
                parsed_value = dateutil_parser.parse(value)
                return parsed_value <= self._db_incremental_field_last_value
            except (ValueError, TypeError):
                return False

        return value <= self._db_incremental_field_last_value

    def update_request(self, request: Request) -> None:
        if self._next_url:
            # Use the full next URL from the Link header
            # Clear params since the next URL already contains all query parameters
            request.url = self._next_url
            request.params = {}


def validate_credentials(personal_access_token: str, repository: str) -> tuple[bool, str | None]:
    """Validate GitHub API credentials by making a test request to the repository."""
    url = f"https://api.github.com/repos/{repository}"
    headers = {
        "Authorization": f"Bearer {personal_access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            return True, None

        if response.status_code == 401:
            return False, "Invalid personal access token"

        if response.status_code == 404:
            return False, f"Repository '{repository}' not found or not accessible"

        try:
            error_data = response.json()
            message = error_data.get("message", response.text)
            return False, message
        except Exception:
            pass

        return False, response.text
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _flatten_commit(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten commit data by extracting nested author/committer info."""
    # Extract commit message and dates from nested commit object
    if "commit" in item and isinstance(item["commit"], dict):
        commit_data = item["commit"]
        item["message"] = commit_data.get("message")

        # Extract author info
        if "author" in commit_data and isinstance(commit_data["author"], dict):
            item["author_name"] = commit_data["author"].get("name")
            item["author_email"] = commit_data["author"].get("email")
            item["created_at"] = commit_data["author"].get("date")

        # Extract committer info
        if "committer" in commit_data and isinstance(commit_data["committer"], dict):
            item["committer_name"] = commit_data["committer"].get("name")
            item["committer_email"] = commit_data["committer"].get("email")
            item["committed_at"] = commit_data["committer"].get("date")

    # Flatten author user info
    if "author" in item and isinstance(item["author"], dict):
        item["author_id"] = item["author"].get("id")
        item["author_login"] = item["author"].get("login")

    # Flatten committer user info
    if "committer" in item and isinstance(item["committer"], dict):
        item["committer_id"] = item["committer"].get("id")
        item["committer_login"] = item["committer"].get("login")

    return item


def _flatten_stargazer(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten stargazer data when using starred_at timestamp."""
    # When using Accept: application/vnd.github.star+json header,
    # response includes starred_at and nested user object
    if "user" in item and isinstance(item["user"], dict):
        user = item.pop("user")
        item["id"] = user["id"]
        item["login"] = user.get("login")
        item["avatar_url"] = user.get("avatar_url")
        item["type"] = user.get("type")
    return item


def _is_issue_not_pr(item: dict[str, Any]) -> bool:
    """Filter predicate to exclude pull requests from the issues endpoint.

    GitHub's Issues API returns both issues and PRs. PRs can be identified
    by the presence of the 'pull_request' key in the response.
    """
    return "pull_request" not in item or item["pull_request"] is None


def _get_item_mapper(endpoint: str):
    """Get the appropriate item mapper for the endpoint."""
    if endpoint == "commits":
        return _flatten_commit
    if endpoint == "stargazers":
        return _flatten_stargazer
    return None


def _get_item_filter(endpoint: str):
    """Get the appropriate item filter for the endpoint."""
    if endpoint == "issues":
        return _is_issue_not_pr
    return None


def github_source(
    personal_access_token: str,
    repository: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = GITHUB_ENDPOINTS[endpoint]

    # Special headers for stargazers to get starred_at timestamp
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if endpoint == "stargazers":
        headers["Accept"] = "application/vnd.github.star+json"

    paginator_incremental_field = None
    paginator_db_incremental_field_last_value = None
    if endpoint_config.sort_mode == "desc" and should_use_incremental_field:
        paginator_incremental_field = incremental_field or endpoint_config.default_incremental_field
        paginator_db_incremental_field_last_value = db_incremental_field_last_value

    config: RESTAPIConfig = {
        "client": {
            "base_url": "https://api.github.com",
            "auth": {
                "type": "bearer",
                "token": personal_access_token,
            },
            "headers": headers,
            "paginator": GithubPaginator(
                incremental_field=paginator_incremental_field,
                db_incremental_field_last_value=paginator_db_incremental_field_last_value,
                sort_mode=endpoint_config.sort_mode,
            ),
        },
        "resource_defaults": {
            "primary_key": "id",
            "write_disposition": "replace",
            "endpoint": {
                "params": {
                    "per_page": endpoint_config.page_size,
                },
            },
        },
        "resources": [
            get_resource(
                endpoint,
                repository,
                should_use_incremental_field,
                db_incremental_field_last_value,
                incremental_field,
            )
        ],
    }

    resources = rest_api_resources(config, team_id, job_id, db_incremental_field_last_value)
    assert len(resources) == 1

    resource = resources[0]

    # Apply filter if endpoint has one (e.g., issues filters out PRs)
    item_filter = _get_item_filter(endpoint)
    if item_filter:
        resource = resource.add_filter(item_filter)

    # Apply mapper if endpoint has one (e.g., commits flattens nested data)
    item_mapper = _get_item_mapper(endpoint)
    if item_mapper:
        resource = resource.add_map(item_mapper)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
