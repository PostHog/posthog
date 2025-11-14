import time
from collections.abc import Iterator
from typing import Any

import requests
import structlog

logger = structlog.get_logger(__name__)

NOTION_API_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"


class NotionClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        }

    def _make_request(
        self, method: str, endpoint: str, params: dict[str, Any] | None = None, json_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a request to the Notion API with retry logic."""
        url = f"{BASE_URL}/{endpoint}"
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=json_data,
                    timeout=30,
                )

                if response.status_code == 429:
                    # Rate limited
                    retry_after = int(response.headers.get("Retry-After", retry_delay))
                    logger.warning(f"Rate limited by Notion API. Retrying after {retry_after} seconds")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(retry_delay * (attempt + 1))

        raise Exception("Max retries exceeded")

    def search(
        self,
        query: str | None = None,
        filter_type: str | None = None,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """Search for pages and databases."""
        json_data: dict[str, Any] = {"page_size": page_size}

        if query:
            json_data["query"] = query

        if filter_type:
            json_data["filter"] = {"value": filter_type, "property": "object"}

        if start_cursor:
            json_data["start_cursor"] = start_cursor

        return self._make_request("POST", "search", json_data=json_data)

    def list_users(self, start_cursor: str | None = None, page_size: int = 100) -> dict[str, Any]:
        """List all users in the workspace."""
        params: dict[str, Any] = {"page_size": page_size}

        if start_cursor:
            params["start_cursor"] = start_cursor

        return self._make_request("GET", "users", params=params)

    def get_page(self, page_id: str) -> dict[str, Any]:
        """Retrieve a specific page."""
        return self._make_request("GET", f"pages/{page_id}")

    def get_database(self, database_id: str) -> dict[str, Any]:
        """Retrieve a specific database."""
        return self._make_request("GET", f"databases/{database_id}")

    def query_database(
        self,
        database_id: str,
        start_cursor: str | None = None,
        page_size: int = 100,
        filter_dict: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Query a database for its pages."""
        json_data: dict[str, Any] = {"page_size": page_size}

        if start_cursor:
            json_data["start_cursor"] = start_cursor

        if filter_dict:
            json_data["filter"] = filter_dict

        if sorts:
            json_data["sorts"] = sorts

        return self._make_request("POST", f"databases/{database_id}/query", json_data=json_data)

    def get_block(self, block_id: str) -> dict[str, Any]:
        """Retrieve a specific block."""
        return self._make_request("GET", f"blocks/{block_id}")

    def get_block_children(
        self, block_id: str, start_cursor: str | None = None, page_size: int = 100
    ) -> dict[str, Any]:
        """Retrieve children blocks of a block."""
        params: dict[str, Any] = {"page_size": page_size}

        if start_cursor:
            params["start_cursor"] = start_cursor

        return self._make_request("GET", f"blocks/{block_id}/children", params=params)

    def get_comments(self, block_id: str, start_cursor: str | None = None, page_size: int = 100) -> dict[str, Any]:
        """Retrieve comments for a block or page."""
        params: dict[str, Any] = {
            "block_id": block_id,
            "page_size": page_size,
        }

        if start_cursor:
            params["start_cursor"] = start_cursor

        return self._make_request("GET", "comments", params=params)

    def paginate_endpoint(self, endpoint_func: callable, *args, **kwargs) -> Iterator[dict[str, Any]]:
        """Generic pagination helper for Notion API endpoints."""
        has_more = True
        start_cursor = None

        while has_more:
            response = endpoint_func(*args, start_cursor=start_cursor, **kwargs)

            results = response.get("results", [])
            yield from results

            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")


def validate_credentials(access_token: str) -> bool:
    """Validate Notion credentials by making a test API call."""
    try:
        client = NotionClient(access_token)
        # Try to list users to validate the token
        client.list_users(page_size=1)
        return True
    except Exception:
        logger.exception("Failed to validate Notion credentials")
        return False
