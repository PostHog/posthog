import copy
import logging
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from requests import Request, Response
from requests.auth import AuthBase

from .exceptions import IgnoreResponseException
from .jsonpath_utils import TJsonPath, find_values
from .paginators import BasePaginator

logger = logging.getLogger(__name__)

Hooks = dict[str, list[Any]]


class RESTClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        auth: Optional[AuthBase] = None,
        paginator: Optional[BasePaginator] = None,
    ) -> None:
        self.base_url = base_url or ""
        self.headers = headers or {}
        self.auth = auth
        self.paginator = paginator
        self.session = requests.Session()
        if self.headers:
            self.session.headers.update(self.headers)

    def _join_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        base = self.base_url
        if not base.endswith("/"):
            base += "/"
        return urljoin(base, path.lstrip("/"))

    def paginate(
        self,
        path: str = "",
        method: str = "get",
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        paginator: Optional[BasePaginator] = None,
        data_selector: Optional[TJsonPath] = None,
        hooks: Optional[Hooks] = None,
    ) -> Iterator[list[Any]]:
        paginator = copy.deepcopy(paginator) if paginator else copy.deepcopy(self.paginator)
        hooks = hooks or {}

        # `requests` serializes None values as the literal string "None" in the
        # query string — drop them so optional/incremental params that are not
        # set don't leak into the URL.
        request_params = {key: value for key, value in (params or {}).items() if value is not None}

        request = Request(
            method=method.upper(),
            url=self._join_url(path),
            params=request_params,
            json=json,
            auth=self.auth,
        )

        if paginator:
            paginator.init_request(request)

        while True:
            try:
                response = self._send_request(request, hooks)
            except IgnoreResponseException:
                break

            data = self._extract_response(response, data_selector)

            if paginator is not None:
                paginator.update_state(response, data)
                paginator.update_request(request)

            yield data

            if paginator is None or not paginator.has_next_page:
                break

    def _send_request(self, request: Request, hooks: Hooks) -> Response:
        prepared = self.session.prepare_request(request)
        response = self.session.send(prepared)

        response_hooks = hooks.get("response", [])
        if response_hooks:
            for hook in response_hooks:
                hook(response, request=request)
        else:
            response.raise_for_status()

        return response

    def _extract_response(self, response: Response, data_selector: Optional[TJsonPath]) -> list[Any]:
        body = response.json()

        if data_selector:
            data: Any = find_values(data_selector, body)
            # unwrap single-item list from jsonpath
            if isinstance(data, list) and len(data) == 1:
                data = data[0]
        else:
            data = body

        if data is None:
            return []
        if not isinstance(data, list):
            data = [data]
        return data
