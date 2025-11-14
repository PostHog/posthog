"""GitLab API client and source implementation"""

from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.gitlab.constants import (
    BRANCH_RESOURCE_NAME,
    COMMIT_RESOURCE_NAME,
    DEFAULT_API_VERSION,
    DEFAULT_BASE_URL,
    GROUP_RESOURCE_NAME,
    ISSUE_RESOURCE_NAME,
    JOB_RESOURCE_NAME,
    MERGE_REQUEST_RESOURCE_NAME,
    MILESTONE_RESOURCE_NAME,
    PIPELINE_RESOURCE_NAME,
    PROJECT_RESOURCE_NAME,
    RELEASE_RESOURCE_NAME,
    TAG_RESOURCE_NAME,
    USER_RESOURCE_NAME,
)

DEFAULT_LIMIT = 100
DEFAULT_TIMEOUT = 30


class GitLabPermissionError(Exception):
    """Raised when GitLab API returns permission errors"""

    pass


class GitLabAPIError(Exception):
    """Raised when GitLab API returns errors"""

    pass


def normalize_base_url(base_url: str) -> str:
    """Normalize the base URL to ensure it's properly formatted"""
    if not base_url:
        return DEFAULT_BASE_URL

    # Add https:// if no scheme is provided
    if not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"

    # Remove trailing slash
    return base_url.rstrip("/")


def build_api_url(base_url: str, path: str) -> str:
    """Build the full API URL"""
    normalized_url = normalize_base_url(base_url)
    api_base = f"{normalized_url}/api/{DEFAULT_API_VERSION}"
    return urljoin(api_base + "/", path.lstrip("/"))


def validate_credentials(access_token: str, base_url: Optional[str] = None) -> bool:
    """Validate GitLab credentials by making a simple API call"""
    try:
        url = build_api_url(base_url or DEFAULT_BASE_URL, "/user")
        headers = {"PRIVATE-TOKEN": access_token}

        response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)

        if response.status_code == 401:
            return False
        elif response.status_code == 403:
            raise GitLabPermissionError("GitLab API token lacks required permissions")
        elif response.status_code >= 400:
            raise GitLabAPIError(f"GitLab API error: {response.status_code} - {response.text}")

        return response.status_code == 200
    except requests.RequestException as e:
        raise GitLabAPIError(f"Failed to connect to GitLab API: {str(e)}")


def get_rows(
    access_token: str,
    base_url: Optional[str],
    project_id: Optional[str],
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
):
    """Fetch rows from GitLab API"""
    normalized_base_url = normalize_base_url(base_url or DEFAULT_BASE_URL)
    headers = {"PRIVATE-TOKEN": access_token}
    batcher = Batcher(logger=logger)

    # Build the API endpoint URL
    if endpoint in [
        ISSUE_RESOURCE_NAME,
        MERGE_REQUEST_RESOURCE_NAME,
        PIPELINE_RESOURCE_NAME,
        JOB_RESOURCE_NAME,
        COMMIT_RESOURCE_NAME,
        BRANCH_RESOURCE_NAME,
        TAG_RESOURCE_NAME,
        RELEASE_RESOURCE_NAME,
        MILESTONE_RESOURCE_NAME,
    ]:
        # Project-scoped endpoints
        if not project_id:
            raise ValueError(f"{endpoint} requires a project_id")
        api_path = f"/projects/{requests.utils.quote(project_id, safe='')}/{endpoint}"
    elif endpoint == PROJECT_RESOURCE_NAME:
        # If project_id is provided, get specific project, otherwise list all
        if project_id:
            api_path = f"/projects/{requests.utils.quote(project_id, safe='')}"
        else:
            api_path = f"/projects"
    elif endpoint in [USER_RESOURCE_NAME, GROUP_RESOURCE_NAME]:
        # Global endpoints
        api_path = f"/{endpoint}"
    else:
        raise ValueError(f"Unsupported endpoint: {endpoint}")

    url = build_api_url(normalized_base_url, api_path)

    # Pagination parameters
    params: dict[str, Any] = {"per_page": DEFAULT_LIMIT, "page": 1}

    # Add incremental field filter if needed
    if should_use_incremental_field and db_incremental_field_last_value:
        # GitLab uses 'updated_after' or 'created_after' for filtering
        if endpoint in [ISSUE_RESOURCE_NAME, MERGE_REQUEST_RESOURCE_NAME]:
            params["updated_after"] = db_incremental_field_last_value
        elif endpoint in [PROJECT_RESOURCE_NAME]:
            params["last_activity_after"] = db_incremental_field_last_value

    # Add sorting to ensure consistent ordering
    if endpoint in [ISSUE_RESOURCE_NAME, MERGE_REQUEST_RESOURCE_NAME]:
        params["order_by"] = "updated_at"
        params["sort"] = "asc"
    elif endpoint == PROJECT_RESOURCE_NAME:
        params["order_by"] = "last_activity_at"
        params["sort"] = "asc"

    logger.info(
        f"Fetching {endpoint} from GitLab",
        endpoint=endpoint,
        project_id=project_id,
        incremental=should_use_incremental_field,
    )

    while True:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)

            if response.status_code == 401:
                raise GitLabPermissionError("Invalid GitLab access token")
            elif response.status_code == 403:
                raise GitLabPermissionError("GitLab API token lacks required permissions")
            elif response.status_code == 404:
                raise GitLabAPIError(f"GitLab resource not found: {url}")
            elif response.status_code >= 400:
                raise GitLabAPIError(f"GitLab API error: {response.status_code} - {response.text}")

            data = response.json()

            # Handle single object vs list
            if isinstance(data, dict):
                # Single project response
                yield from batcher.process([data])
                break
            elif isinstance(data, list):
                if not data:
                    # No more data
                    break

                yield from batcher.process(data)

                # Check for next page
                # GitLab uses Link headers for pagination
                link_header = response.headers.get("Link", "")
                if "rel=\"next\"" not in link_header:
                    break

                params["page"] += 1
            else:
                logger.warning(f"Unexpected response type from GitLab API: {type(data)}")
                break

        except requests.RequestException as e:
            raise GitLabAPIError(f"Failed to fetch data from GitLab: {str(e)}")

    # Flush any remaining items
    yield from batcher.flush()


def gitlab_source(
    access_token: str,
    base_url: Optional[str],
    project_id: Optional[str],
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """Main GitLab source function"""

    def items_generator():
        yield from get_rows(
            access_token=access_token,
            base_url=base_url,
            project_id=project_id,
            endpoint=endpoint,
            db_incremental_field_last_value=db_incremental_field_last_value,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
        )

    # Determine primary keys based on endpoint
    primary_keys_map = {
        PROJECT_RESOURCE_NAME: ["id"],
        ISSUE_RESOURCE_NAME: ["id"],
        MERGE_REQUEST_RESOURCE_NAME: ["id"],
        PIPELINE_RESOURCE_NAME: ["id"],
        JOB_RESOURCE_NAME: ["id"],
        COMMIT_RESOURCE_NAME: ["id"],
        BRANCH_RESOURCE_NAME: ["name"],
        TAG_RESOURCE_NAME: ["name"],
        RELEASE_RESOURCE_NAME: ["tag_name"],
        MILESTONE_RESOURCE_NAME: ["id"],
        USER_RESOURCE_NAME: ["id"],
        GROUP_RESOURCE_NAME: ["id"],
    }

    # Determine partition keys (use created_at for most endpoints)
    partition_keys_map = {
        PROJECT_RESOURCE_NAME: ["created_at"],
        ISSUE_RESOURCE_NAME: ["created_at"],
        MERGE_REQUEST_RESOURCE_NAME: ["created_at"],
        PIPELINE_RESOURCE_NAME: ["created_at"],
        JOB_RESOURCE_NAME: ["created_at"],
        COMMIT_RESOURCE_NAME: ["created_at"],
        RELEASE_RESOURCE_NAME: ["created_at"],
        MILESTONE_RESOURCE_NAME: ["created_at"],
        USER_RESOURCE_NAME: ["created_at"],
    }

    return SourceResponse(
        items=items_generator(),
        primary_keys=primary_keys_map.get(endpoint, ["id"]),
        partition_keys=partition_keys_map.get(endpoint),
        partition_mode="datetime" if endpoint in partition_keys_map else None,
        partition_format="month" if endpoint in partition_keys_map else None,
    )
