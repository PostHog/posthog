import time
from datetime import datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.github.constants import (
    BRANCHES_RESOURCE_NAME,
    COLLABORATORS_RESOURCE_NAME,
    COMMITS_RESOURCE_NAME,
    EVENTS_RESOURCE_NAME,
    ISSUE_COMMENTS_RESOURCE_NAME,
    ISSUES_RESOURCE_NAME,
    PULL_REQUEST_COMMITS_RESOURCE_NAME,
    PULL_REQUEST_REVIEWS_RESOURCE_NAME,
    PULL_REQUESTS_RESOURCE_NAME,
    RELEASES_RESOURCE_NAME,
    REPOSITORIES_RESOURCE_NAME,
    STARGAZERS_RESOURCE_NAME,
    TAGS_RESOURCE_NAME,
    WORKFLOW_RUNS_RESOURCE_NAME,
    WORKFLOWS_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.github.settings import INCREMENTAL_FIELDS

from products.data_warehouse.backend.models.external_table_definitions import get_dlt_mapping_for_external_table

DEFAULT_PER_PAGE = 100
GITHUB_API_BASE_URL = "https://api.github.com"


class GitHubPermissionError(Exception):
    """Exception raised when GitHub token lacks permissions for specific resources."""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        super().__init__(f"Missing permissions: {', '.join(missing_permissions.keys())}")


class GitHubRateLimitError(Exception):
    """Exception raised when GitHub API rate limit is exceeded."""

    pass


def get_github_api_headers(access_token: str) -> dict[str, str]:
    """Get standard GitHub API headers."""
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def handle_rate_limit(response: requests.Response, logger: FilteringBoundLogger) -> None:
    """Handle GitHub API rate limiting."""
    if response.status_code == 403:
        rate_limit_remaining = response.headers.get("X-RateLimit-Remaining", "0")
        if rate_limit_remaining == "0":
            reset_timestamp = int(response.headers.get("X-RateLimit-Reset", "0"))
            if reset_timestamp:
                reset_time = datetime.fromtimestamp(reset_timestamp)
                wait_seconds = max(0, (reset_time - datetime.now()).total_seconds())
                logger.warning(f"GitHub rate limit exceeded. Waiting {wait_seconds:.0f} seconds until {reset_time}")
                if wait_seconds > 0:
                    time.sleep(wait_seconds + 1)  # Add 1 second buffer
            else:
                raise GitHubRateLimitError("GitHub API rate limit exceeded")


def make_github_request(
    url: str,
    access_token: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> requests.Response:
    """Make a GitHub API request with rate limit handling."""
    headers = get_github_api_headers(access_token)
    response = requests.get(url, headers=headers, params=params, timeout=30)

    if response.status_code == 403:
        handle_rate_limit(response, logger)
        # Retry after handling rate limit
        response = requests.get(url, headers=headers, params=params, timeout=30)

    response.raise_for_status()
    return response


def get_next_page_url(response: requests.Response) -> str | None:
    """Extract next page URL from GitHub API Link header."""
    link_header = response.headers.get("Link", "")
    if not link_header:
        return None

    links = {}
    for part in link_header.split(","):
        section = part.split(";")
        if len(section) == 2:
            url = section[0].strip()[1:-1]  # Remove < >
            rel = section[1].strip().split("=")[1][1:-1]  # Remove 'rel="..."'
            links[rel] = url

    return links.get("next")


def validate_credentials(access_token: str, repository: str) -> bool:
    """Validate GitHub credentials by making a test API call."""
    try:
        headers = get_github_api_headers(access_token)
        response = requests.get(f"{GITHUB_API_BASE_URL}/repos/{repository}", headers=headers, timeout=30)

        if response.status_code == 404:
            return False
        elif response.status_code == 401:
            return False

        response.raise_for_status()
        return True
    except requests.exceptions.RequestException:
        return False


def get_endpoint_url(repository: str, endpoint: str) -> str:
    """Get the full API URL for a given endpoint."""
    endpoint_urls = {
        ISSUES_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/issues",
        PULL_REQUESTS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls",
        COMMITS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/commits",
        ISSUE_COMMENTS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/issues/comments",
        PULL_REQUEST_REVIEWS_RESOURCE_NAME: None,  # Requires pull number
        PULL_REQUEST_COMMITS_RESOURCE_NAME: None,  # Requires pull number
        REPOSITORIES_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}",
        COLLABORATORS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/collaborators",
        EVENTS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/events",
        RELEASES_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/releases",
        STARGAZERS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/stargazers",
        BRANCHES_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/branches",
        TAGS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/tags",
        WORKFLOWS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/actions/workflows",
        WORKFLOW_RUNS_RESOURCE_NAME: f"{GITHUB_API_BASE_URL}/repos/{repository}/actions/runs",
    }

    url = endpoint_urls.get(endpoint)
    if url is None:
        raise ValueError(f"Endpoint {endpoint} not supported or requires additional parameters")

    return url


def get_rows(
    access_token: str,
    repository: str,
    endpoint: str,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
):
    """Fetch rows from GitHub API for a given endpoint."""
    batcher = Batcher(logger=logger)

    # Handle special case endpoints
    if endpoint == REPOSITORIES_RESOURCE_NAME:
        # Single repository endpoint
        url = get_endpoint_url(repository, endpoint)
        response = make_github_request(url, access_token, {}, logger)
        data = response.json()
        yield data
        return

    if endpoint in [PULL_REQUEST_REVIEWS_RESOURCE_NAME, PULL_REQUEST_COMMITS_RESOURCE_NAME]:
        # These require fetching pull requests first, then their nested resources
        yield from get_nested_pull_request_resource(access_token, repository, endpoint, logger)
        return

    # Standard pagination-based endpoints
    url = get_endpoint_url(repository, endpoint)
    params: dict[str, Any] = {"per_page": DEFAULT_PER_PAGE, "page": 1}

    # Add incremental field filtering if applicable
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    if should_use_incremental_field and db_incremental_field_last_value and incremental_field_config:
        params["since"] = db_incremental_field_last_value

    # Special parameters for specific endpoints
    if endpoint == ISSUES_RESOURCE_NAME:
        params["state"] = "all"  # Get both open and closed issues
        params["sort"] = "updated"
        params["direction"] = "asc"
    elif endpoint == PULL_REQUESTS_RESOURCE_NAME:
        params["state"] = "all"  # Get both open and closed PRs
        params["sort"] = "updated"
        params["direction"] = "asc"
    elif endpoint == STARGAZERS_RESOURCE_NAME:
        # Need special accept header for starred_at timestamp
        params["Accept"] = "application/vnd.github.star+json"

    while url:
        response = make_github_request(url, access_token, params, logger)
        data = response.json()

        # Handle different response structures
        if isinstance(data, dict) and "workflows" in data:
            # Workflows endpoint returns wrapped data
            items = data["workflows"]
        elif isinstance(data, dict) and "workflow_runs" in data:
            # Workflow runs endpoint returns wrapped data
            items = data["workflow_runs"]
        elif isinstance(data, list):
            items = data
        else:
            items = [data]

        for item in items:
            batcher.batch(item)

            if batcher.should_yield():
                yield batcher.get_table()

        # Get next page URL from Link header
        url = get_next_page_url(response)
        params = {}  # Clear params for next page URL (it includes all params)

    # Yield any remaining items
    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def get_nested_pull_request_resource(
    access_token: str,
    repository: str,
    endpoint: str,
    logger: FilteringBoundLogger,
):
    """Fetch nested pull request resources (reviews or commits)."""
    batcher = Batcher(logger=logger)

    # First, get all pull requests
    pulls_url = f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls"
    params: dict[str, Any] = {"per_page": DEFAULT_PER_PAGE, "state": "all", "page": 1}

    while pulls_url:
        response = make_github_request(pulls_url, access_token, params, logger)
        pull_requests = response.json()

        for pr in pull_requests:
            pr_number = pr["number"]

            # Fetch nested resource for this PR
            if endpoint == PULL_REQUEST_REVIEWS_RESOURCE_NAME:
                nested_url = f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls/{pr_number}/reviews"
            elif endpoint == PULL_REQUEST_COMMITS_RESOURCE_NAME:
                nested_url = f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls/{pr_number}/commits"
            else:
                continue

            nested_params = {"per_page": DEFAULT_PER_PAGE, "page": 1}

            while nested_url:
                nested_response = make_github_request(nested_url, access_token, nested_params, logger)
                nested_items = nested_response.json()

                for item in nested_items:
                    # Add PR number to the item for reference
                    item["pull_request_number"] = pr_number
                    batcher.batch(item)

                    if batcher.should_yield():
                        yield batcher.get_table()

                # Get next page for nested resource
                nested_url = get_next_page_url(nested_response)
                nested_params = {}

        # Get next page for pull requests
        pulls_url = get_next_page_url(response)
        params = {}

    # Yield any remaining items
    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def github_source(
    access_token: str,
    repository: str,
    endpoint: str,
    db_incremental_field_last_value: Any | None,
    db_incremental_field_earliest_value: Any | None,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    """Create a GitHub source for the data pipeline."""
    column_mapping = get_dlt_mapping_for_external_table(f"github_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    # Get the incremental field name for partition keys
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    # Determine primary keys based on endpoint
    if endpoint == REPOSITORIES_RESOURCE_NAME:
        primary_keys = ["id"]
    elif endpoint in [PULL_REQUEST_REVIEWS_RESOURCE_NAME, PULL_REQUEST_COMMITS_RESOURCE_NAME]:
        primary_keys = ["id", "pull_request_number"]
    else:
        primary_keys = ["id"]

    response = SourceResponse(
        items=lambda: get_rows(
            access_token=access_token,
            repository=repository,
            endpoint=endpoint,
            db_incremental_field_last_value=db_incremental_field_last_value,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
        ),
        primary_keys=primary_keys,
        name=endpoint,
        column_hints=column_hints,
        sort_mode="asc",  # GitHub returns in ascending order by default
    )

    # Add partitioning for endpoints with incremental fields
    if incremental_field_name:
        response.partition_mode = "datetime"
        response.partition_format = "month"
        response.partition_keys = [incremental_field_name]

    return response
