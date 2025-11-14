import dataclasses
from datetime import datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.github.constants import (
    BRANCHES_RESOURCE_NAME,
    COLLABORATORS_RESOURCE_NAME,
    COMMITS_RESOURCE_NAME,
    EVENTS_RESOURCE_NAME,
    ISSUE_COMMENTS_RESOURCE_NAME,
    ISSUES_RESOURCE_NAME,
    PULL_REQUEST_COMMENTS_RESOURCE_NAME,
    PULL_REQUESTS_RESOURCE_NAME,
    RELEASES_RESOURCE_NAME,
    REVIEWS_RESOURCE_NAME,
    STARGAZERS_RESOURCE_NAME,
    TAGS_RESOURCE_NAME,
    WORKFLOW_RUNS_RESOURCE_NAME,
    WORKFLOWS_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.github.settings import INCREMENTAL_FIELDS


class GitHubAPIError(Exception):
    """Raised when GitHub API returns an error"""

    pass


class GitHubPermissionError(Exception):
    """Raised when GitHub API key lacks required permissions"""

    def __init__(self, missing_permissions: dict[str, str]):
        self.missing_permissions = missing_permissions
        super().__init__(f"Missing permissions: {missing_permissions}")


@dataclasses.dataclass
class GitHubResumeConfig:
    page: int


def validate_credentials(access_token: str, repository: str) -> bool:
    """Validate GitHub credentials by making a test API call"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    response = requests.get(f"https://api.github.com/repos/{repository}", headers=headers)

    if response.status_code == 200:
        return True
    elif response.status_code == 401:
        raise GitHubAPIError("Invalid access token")
    elif response.status_code == 404:
        raise GitHubAPIError("Repository not found or access denied")
    else:
        raise GitHubAPIError(f"API error: {response.status_code} - {response.text}")


def parse_datetime(date_str: str | None) -> datetime | None:
    """Parse GitHub datetime string to datetime object"""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def get_nested_value(obj: dict[str, Any], path: str) -> Any:
    """Get nested value from dict using dot notation path"""
    keys = path.split(".")
    value = obj
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def get_rows(
    access_token: str,
    repository: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
    db_incremental_field_earliest_value: Any | None,
    logger: FilteringBoundLogger,
):
    """Fetch rows from GitHub API"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    per_page = 100
    page = 1

    # Get incremental field config if applicable
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint)
    incremental_field = None
    if incremental_field_config and len(incremental_field_config) > 0:
        incremental_field = incremental_field_config[0]["field"]

    # Build the API URL based on endpoint
    base_url = f"https://api.github.com/repos/{repository}"

    endpoint_urls = {
        ISSUES_RESOURCE_NAME: f"{base_url}/issues",
        PULL_REQUESTS_RESOURCE_NAME: f"{base_url}/pulls",
        COMMITS_RESOURCE_NAME: f"{base_url}/commits",
        ISSUE_COMMENTS_RESOURCE_NAME: f"{base_url}/issues/comments",
        PULL_REQUEST_COMMENTS_RESOURCE_NAME: f"{base_url}/pulls/comments",
        RELEASES_RESOURCE_NAME: f"{base_url}/releases",
        STARGAZERS_RESOURCE_NAME: f"{base_url}/stargazers",
        EVENTS_RESOURCE_NAME: f"{base_url}/events",
        WORKFLOWS_RESOURCE_NAME: f"{base_url}/actions/workflows",
        WORKFLOW_RUNS_RESOURCE_NAME: f"{base_url}/actions/runs",
        BRANCHES_RESOURCE_NAME: f"{base_url}/branches",
        TAGS_RESOURCE_NAME: f"{base_url}/tags",
        COLLABORATORS_RESOURCE_NAME: f"{base_url}/collaborators",
    }

    # Special handling for reviews (needs PR numbers)
    if endpoint == REVIEWS_RESOURCE_NAME:
        yield from get_reviews(
            access_token, repository, should_use_incremental_field, db_incremental_field_last_value, logger
        )
        return

    url = endpoint_urls.get(endpoint)
    if not url:
        raise GitHubAPIError(f"Unknown endpoint: {endpoint}")

    # Add special headers for certain endpoints
    if endpoint == STARGAZERS_RESOURCE_NAME:
        headers["Accept"] = "application/vnd.github.star+json"

    params: dict[str, Any] = {"per_page": per_page, "page": page}

    # Add state filter for issues and PRs
    if endpoint in [ISSUES_RESOURCE_NAME, PULL_REQUESTS_RESOURCE_NAME]:
        params["state"] = "all"

    # Add sorting for incremental sync
    if should_use_incremental_field and incremental_field:
        if endpoint in [ISSUES_RESOURCE_NAME, PULL_REQUESTS_RESOURCE_NAME]:
            params["sort"] = "updated"
            params["direction"] = "asc"

        # Add since parameter if we have a last value
        if db_incremental_field_last_value:
            try:
                if isinstance(db_incremental_field_last_value, datetime):
                    since_date = db_incremental_field_last_value
                else:
                    since_date = parse_datetime(str(db_incremental_field_last_value))

                if since_date and endpoint in [ISSUES_RESOURCE_NAME, PULL_REQUESTS_RESOURCE_NAME]:
                    params["since"] = since_date.isoformat()
            except Exception as e:
                logger.warning(f"Error parsing incremental field value: {e}")

    while True:
        params["page"] = page
        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            raise GitHubAPIError(f"API error: {response.status_code} - {response.text}")

        data = response.json()

        # Handle workflows endpoint which returns a different structure
        if endpoint == WORKFLOWS_RESOURCE_NAME and isinstance(data, dict):
            data = data.get("workflows", [])
        elif endpoint == WORKFLOW_RUNS_RESOURCE_NAME and isinstance(data, dict):
            data = data.get("workflow_runs", [])

        if not data or len(data) == 0:
            break

        # Filter by incremental field if needed
        filtered_data = []
        for item in data:
            if should_use_incremental_field and incremental_field and db_incremental_field_last_value:
                item_value = get_nested_value(item, incremental_field)
                if item_value:
                    item_date = parse_datetime(item_value)
                    last_value_date = (
                        db_incremental_field_last_value
                        if isinstance(db_incremental_field_last_value, datetime)
                        else parse_datetime(str(db_incremental_field_last_value))
                    )
                    if item_date and last_value_date and item_date <= last_value_date:
                        continue
            filtered_data.append(item)

        if filtered_data:
            yield filtered_data

        # Check if there are more pages
        link_header = response.headers.get("Link", "")
        if 'rel="next"' not in link_header:
            break

        page += 1


def get_reviews(
    access_token: str,
    repository: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
):
    """Fetch reviews for all pull requests"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # First, get all pull requests
    pr_url = f"https://api.github.com/repos/{repository}/pulls"
    params = {"state": "all", "per_page": 100, "page": 1}

    while True:
        pr_response = requests.get(pr_url, headers=headers, params=params)
        if pr_response.status_code != 200:
            raise GitHubAPIError(f"API error fetching PRs: {pr_response.status_code} - {pr_response.text}")

        prs = pr_response.json()
        if not prs:
            break

        # For each PR, fetch its reviews
        for pr in prs:
            pr_number = pr["number"]
            reviews_url = f"https://api.github.com/repos/{repository}/pulls/{pr_number}/reviews"
            reviews_response = requests.get(reviews_url, headers=headers)

            if reviews_response.status_code == 200:
                reviews = reviews_response.json()
                if reviews:
                    # Filter by incremental field if needed
                    filtered_reviews = []
                    for review in reviews:
                        if should_use_incremental_field and db_incremental_field_last_value:
                            submitted_at = review.get("submitted_at")
                            if submitted_at:
                                review_date = parse_datetime(submitted_at)
                                last_value_date = (
                                    db_incremental_field_last_value
                                    if isinstance(db_incremental_field_last_value, datetime)
                                    else parse_datetime(str(db_incremental_field_last_value))
                                )
                                if review_date and last_value_date and review_date <= last_value_date:
                                    continue
                        filtered_reviews.append(review)

                    if filtered_reviews:
                        yield filtered_reviews

        # Check for next page
        link_header = pr_response.headers.get("Link", "")
        if 'rel="next"' not in link_header:
            break

        params["page"] += 1


def github_source(
    access_token: str,
    repository: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
    db_incremental_field_earliest_value: Any | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """Main function to create GitHub source"""

    def items():
        yield from get_rows(
            access_token=access_token,
            repository=repository,
            endpoint=endpoint,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            db_incremental_field_earliest_value=db_incremental_field_earliest_value,
            logger=logger,
        )

    incremental_config = INCREMENTAL_FIELDS.get(endpoint)
    primary_key = ["id"]

    return SourceResponse(
        items=items(),
        primary_keys=primary_key,
        incremental_field=incremental_config[0]["field"] if incremental_config else None,
    )
