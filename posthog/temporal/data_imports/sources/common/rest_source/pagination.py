"""
Pagination implementations for REST API sources.

Replaces DLT's pagination classes with simplified versions that maintain
the same external API.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

import requests


class BasePaginator(ABC):
    """Base class for API paginators.

    This replaces dlt.sources.helpers.rest_client.paginators.BasePaginator
    with a compatible interface.
    """

    def __init__(self):
        self._has_next_page = True

    @property
    def has_next_page(self) -> bool:
        """Whether there are more pages to fetch."""
        return self._has_next_page

    @abstractmethod
    def update_state(self, response: requests.Response, data: Optional[Any] = None) -> None:
        """Update pagination state based on the response.

        Args:
            response: The HTTP response object
            data: Optional extracted data from the response
        """
        pass

    @abstractmethod
    def update_request(self, request: requests.Request) -> None:
        """Modify the request for the next page.

        Args:
            request: The request object to modify
        """
        pass


class SinglePagePaginator(BasePaginator):
    """Paginator for single-page responses (no pagination)."""

    def __init__(self):
        super().__init__()
        self._first_request = True

    def update_state(self, response: requests.Response, data: Optional[Any] = None) -> None:
        self._has_next_page = False

    def update_request(self, request: requests.Request) -> None:
        if self._first_request:
            self._first_request = False
        else:
            self._has_next_page = False


class OffsetPaginator(BasePaginator):
    """Offset-based pagination (e.g., offset=0&limit=100).

    Compatible with dlt.sources.helpers.rest_client.paginators.OffsetPaginator
    """

    def __init__(
        self,
        limit: int = 100,
        offset: int = 0,
        offset_param: str = "offset",
        limit_param: str = "limit",
        total_path: Optional[str] = None,
    ):
        super().__init__()
        self.limit = limit
        self.offset = offset
        self.offset_param = offset_param
        self.limit_param = limit_param
        self.total_path = total_path
        self._total: Optional[int] = None

    def update_state(self, response: requests.Response, data: Optional[Any] = None) -> None:
        from .jsonpath_utils import extract_value

        self.offset += self.limit

        # Try to get total from response data
        if self.total_path and data:
            total_value = extract_value(data, self.total_path)
            if total_value is not None:
                self._total = int(total_value)

        # Determine if there's a next page
        if self._total is not None:
            self._has_next_page = self.offset < self._total
        else:
            # No total - we'll rely on getting empty/fewer results to stop pagination
            # This is a conservative approach - keep paginating until we get no data
            self._has_next_page = True

    def update_request(self, request: requests.Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.offset_param] = self.offset
        request.params[self.limit_param] = self.limit


class PageNumberPaginator(BasePaginator):
    """Page number-based pagination (e.g., page=1&per_page=100).

    Compatible with dlt.sources.helpers.rest_client.paginators.PageNumberPaginator
    """

    def __init__(
        self,
        base_page: int = 1,
        page: Optional[int] = None,
        page_param: str = "page",
        per_page: int = 100,
        per_page_param: str = "per_page",
        total_path: Optional[str] = None,
    ):
        super().__init__()
        self.base_page = base_page
        self.page = page or base_page
        self.page_param = page_param
        self.per_page = per_page
        self.per_page_param = per_page_param
        self.total_path = total_path
        self._total_pages: Optional[int] = None

    def update_state(self, response: requests.Response, data: Optional[Any] = None) -> None:
        from .jsonpath_utils import extract_value

        self.page += 1

        # Try to get total pages from response
        if self.total_path and data:
            self._total_pages = extract_value(data, self.total_path)

        # Determine if there's a next page
        if self._total_pages is not None:
            self._has_next_page = self.page <= self._total_pages
        elif data is not None:
            # No total - check if we got fewer items than per_page
            items = data if isinstance(data, list) else []
            self._has_next_page = len(items) >= self.per_page
        else:
            self._has_next_page = False

    def update_request(self, request: requests.Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page
        request.params[self.per_page_param] = self.per_page


class JSONResponsePaginator(BasePaginator):
    """Paginator that extracts next page URL from JSON response.

    Compatible with dlt.sources.helpers.rest_client.paginators.JSONResponsePaginator
    """

    def __init__(self, next_url_path: str = "next"):
        super().__init__()
        self.next_url_path = next_url_path
        self._next_url: Optional[str] = None

    def update_state(self, response: requests.Response, data: Optional[Any] = None) -> None:
        from .jsonpath_utils import extract_value

        if data:
            self._next_url = extract_value(data, self.next_url_path)
            self._has_next_page = self._next_url is not None
        else:
            self._has_next_page = False

    def update_request(self, request: requests.Request) -> None:
        if self._next_url:
            request.url = self._next_url


class JSONResponseCursorPaginator(BasePaginator):
    """Cursor-based pagination using JSON response field.

    Compatible with dlt.sources.helpers.rest_client.paginators.JSONResponseCursorPaginator
    """

    def __init__(
        self,
        cursor_path: str = "next_cursor",
        cursor_param: str = "cursor",
    ):
        super().__init__()
        self.cursor_path = cursor_path
        self.cursor_param = cursor_param
        self._cursor: Optional[str] = None

    def update_state(self, response: requests.Response, data: Optional[Any] = None) -> None:
        from .jsonpath_utils import extract_value

        if data:
            cursor = extract_value(data, self.cursor_path)
            if cursor:
                self._cursor = str(cursor)
                self._has_next_page = True
            else:
                self._has_next_page = False
        else:
            self._has_next_page = False

    def update_request(self, request: requests.Request) -> None:
        if self._cursor:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor


class HeaderLinkPaginator(BasePaginator):
    """Paginator that follows Link headers (RFC 5988).

    Compatible with dlt.sources.helpers.rest_client.paginators.HeaderLinkPaginator
    """

    def __init__(self, links_next_key: str = "next"):
        super().__init__()
        self.links_next_key = links_next_key
        self._next_url: Optional[str] = None

    def update_state(self, response: requests.Response, data: Optional[Any] = None) -> None:
        link_header = response.headers.get("Link", "")
        self._next_url = self._parse_link_header(link_header, self.links_next_key)
        self._has_next_page = self._next_url is not None

    def update_request(self, request: requests.Request) -> None:
        if self._next_url:
            request.url = self._next_url

    @staticmethod
    def _parse_link_header(link_header: str, rel: str) -> Optional[str]:
        """Parse Link header to extract URL with specified rel."""
        if not link_header:
            return None

        for link in link_header.split(","):
            parts = link.split(";")
            if len(parts) < 2:
                continue

            url = parts[0].strip().strip("<>")
            params = {}
            for part in parts[1:]:
                if "=" in part:
                    key, value = part.split("=", 1)
                    params[key.strip()] = value.strip().strip('"')

            if params.get("rel") == rel:
                return url

        return None


# Alias for DLT compatibility
JSONLinkPaginator = JSONResponsePaginator
