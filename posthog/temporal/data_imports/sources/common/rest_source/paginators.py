import re
from abc import ABC, abstractmethod
from typing import Any, Optional

from requests import Request, Response

from .jsonpath_utils import TJsonPath, find_values


class BasePaginator(ABC):
    def __init__(self) -> None:
        self._has_next_page = True

    @property
    def has_next_page(self) -> bool:
        return self._has_next_page

    def init_request(self, request: Request) -> None:  # noqa: B027
        pass

    @abstractmethod
    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None: ...

    @abstractmethod
    def update_request(self, request: Request) -> None: ...

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        """Return a JSON-serializable snapshot pointing to the next page, or
        ``None`` if this paginator does not support resume. Sources opt in by
        overriding this together with ``set_resume_state``."""
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:  # noqa: B027
        """Seed this paginator from a previously returned ``get_resume_state``
        value. After seeding, ``init_request`` must emit a request that targets
        the resumed page."""
        pass


class SinglePagePaginator(BasePaginator):
    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._has_next_page = False

    def update_request(self, request: Request) -> None:
        pass


class BaseNextUrlPaginator(BasePaginator):
    def __init__(self) -> None:
        super().__init__()
        self._next_url: Optional[str] = None

    def update_request(self, request: Request) -> None:
        if self._next_url is not None:
            request.url = self._next_url


class HeaderLinkPaginator(BaseNextUrlPaginator):
    def __init__(self, links_next_key: str = "next") -> None:
        super().__init__()
        self.links_next_key = links_next_key

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        links = response.links
        next_link = links.get(self.links_next_key)
        if next_link:
            self._next_url = next_link.get("url")
            self._has_next_page = True
        else:
            self._has_next_page = False

    def __str__(self) -> str:
        return f"HeaderLinkPaginator(links_next_key={self.links_next_key})"


class JSONResponsePaginator(BaseNextUrlPaginator):
    """Locates the next page URL within the JSON response body."""

    def __init__(self, next_url_path: TJsonPath = "next") -> None:
        super().__init__()
        self.next_url_path = next_url_path

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            values = find_values(self.next_url_path, response.json())
        except Exception:
            values = []
        if values and values[0]:
            self._next_url = values[0]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def __str__(self) -> str:
        return f"JSONResponsePaginator(next_url_path={self.next_url_path})"


# Alias used by zendesk
JSONLinkPaginator = JSONResponsePaginator


class JSONResponseCursorPaginator(BasePaginator):
    def __init__(
        self,
        cursor_path: TJsonPath = "cursors.next",
        cursor_param: str = "cursor",
    ) -> None:
        super().__init__()
        self.cursor_path = cursor_path
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            values = find_values(self.cursor_path, response.json())
        except Exception:
            values = []
        if values and values[0]:
            self._cursor_value = values[0]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def __str__(self) -> str:
        return f"JSONResponseCursorPaginator(cursor_path={self.cursor_path})"


class OffsetPaginator(BasePaginator):
    def __init__(
        self,
        limit: int,
        offset: int = 0,
        offset_param: str = "offset",
        limit_param: str = "limit",
        total_path: Optional[TJsonPath] = "total",
        maximum_offset: Optional[int] = None,
        stop_after_empty_page: bool = True,
    ) -> None:
        super().__init__()
        self.limit = limit
        self.offset = offset
        self.offset_param = offset_param
        self.limit_param = limit_param
        self.total_path = total_path
        self.maximum_offset = maximum_offset
        self.stop_after_empty_page = stop_after_empty_page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.offset_param] = self.offset
        request.params[self.limit_param] = self.limit

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if self.stop_after_empty_page and (data is None or len(data) == 0):
            self._has_next_page = False
            return

        self.offset += self.limit

        if self.maximum_offset is not None and self.offset >= self.maximum_offset:
            self._has_next_page = False
            return

        if self.total_path:
            try:
                values = find_values(self.total_path, response.json())
                if values:
                    total = values[0]
                    if isinstance(total, int) and self.offset >= total:
                        self._has_next_page = False
                        return
            except Exception:
                pass

        if data is not None and len(data) < self.limit:
            self._has_next_page = False
            return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.offset_param] = self.offset

    def __str__(self) -> str:
        return f"OffsetPaginator(offset={self.offset}, limit={self.limit})"


class PageNumberPaginator(BasePaginator):
    def __init__(
        self,
        base_page: int = 0,
        page: Optional[int] = None,
        page_param: str = "page",
        total_path: Optional[TJsonPath] = "total",
        maximum_page: Optional[int] = None,
        stop_after_empty_page: bool = True,
    ) -> None:
        super().__init__()
        self.base_page = base_page
        self.page = page if page is not None else base_page
        self.page_param = page_param
        self.total_path = total_path
        self.maximum_page = maximum_page
        self.stop_after_empty_page = stop_after_empty_page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if self.stop_after_empty_page and (data is None or len(data) == 0):
            self._has_next_page = False
            return

        self.page += 1

        if self.maximum_page is not None and self.page > self.maximum_page:
            self._has_next_page = False
            return

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def __str__(self) -> str:
        return f"PageNumberPaginator(page={self.page})"


def single_entity_path(path: str) -> bool:
    """Check if path ends with a {param} pattern, indicating a single entity endpoint."""
    from pathlib import PurePosixPath

    name = PurePosixPath(path).name
    return re.search(r"\{([a-zA-Z0-9._-]+)\}", name) is not None
