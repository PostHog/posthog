"""
HTTP client with pagination support for REST API sources.

Replaces DLT's RESTClient with a simplified version using requests.
"""

from collections.abc import Iterator
from typing import Any, Optional

import requests

from .auth import AuthBase
from .jsonpath_utils import extract_value
from .pagination import BasePaginator


class RESTClient:
    """Simple REST client with pagination and authentication.

    Compatible with dlt.sources.helpers.rest_client.RESTClient
    """

    def __init__(
        self,
        base_url: str,
        auth: Optional[AuthBase] = None,
        paginator: Optional[BasePaginator] = None,
        headers: Optional[dict[str, str]] = None,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.paginator = paginator
        self.headers = headers or {}
        self.session = session or requests.Session()

    def paginate(
        self,
        path: str,
        method: str = "GET",
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        data_selector: Optional[str] = None,
    ) -> Iterator[dict]:
        """Iterate through paginated API responses.

        Args:
            path: API endpoint path (relative to base_url)
            method: HTTP method (GET, POST, etc.)
            params: Query parameters
            json: JSON body for POST requests
            data_selector: JSONPath to extract items from response

        Yields:
            Individual items from the API response
        """
        url = self._build_url(path)

        while True:
            # Create request
            request = requests.Request(
                method=method,
                url=url,
                params=params.copy() if params else {},
                json=json,
            )

            # Let paginator update request for next page
            if self.paginator:
                self.paginator.update_request(request)

            # Prepare and authenticate request
            prepared = self.session.prepare_request(request)
            prepared.headers.update(self.headers)

            if self.auth:
                prepared = self.auth(prepared)

            # Send request
            response = self.session.send(prepared)
            response.raise_for_status()

            # Parse response
            try:
                response_data = response.json()
            except Exception:
                # Non-JSON response
                break

            # Extract items using data_selector
            items = extract_value(response_data, data_selector) if data_selector else response_data

            # Count yielded items for pagination logic
            items_count = 0

            # Yield items
            if isinstance(items, list):
                items_count = len(items)
                yield from items
            elif items is not None:
                items_count = 1
                yield items
            else:
                # No data returned
                break

            # Update pagination state
            if self.paginator:
                # Pass full response_data so paginator can extract total counts, etc.
                self.paginator.update_state(response, response_data)

                # Stop if paginator says no more pages
                if not self.paginator.has_next_page:
                    break

                # Also stop if we got 0 items (indicates end of data)
                if items_count == 0:
                    break
            else:
                # No paginator - single page only
                break

    def _build_url(self, path: str) -> str:
        """Build full URL from base_url and path.

        Args:
            path: Relative path

        Returns:
            Full URL
        """
        path = path.lstrip("/")
        return f"{self.base_url}/{path}"


# For compatibility with code that expects Response type
Response = requests.Response
Request = requests.Request
