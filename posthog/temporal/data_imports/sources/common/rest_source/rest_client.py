import copy
import logging
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import urljoin

from requests import Request, Response, Session
from requests.auth import AuthBase
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt

from posthog.temporal.data_imports.sources.common.http import make_tracked_session

from .exceptions import IgnoreResponseException
from .jsonpath_utils import TJsonPath, find_values
from .paginators import BasePaginator

logger = logging.getLogger(__name__)


class RESTClientRetryableError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _retry_wait_seconds(state: RetryCallState) -> float:
    fallback = min(2 ** (state.attempt_number - 1), 60)
    if state.outcome is None or not state.outcome.failed:
        return float(fallback)
    exc = state.outcome.exception()
    if isinstance(exc, RESTClientRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, 300.0)
    return float(fallback)


Hooks = dict[str, list[Any]]


class RESTClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        auth: Optional[AuthBase] = None,
        paginator: Optional[BasePaginator] = None,
        session: Optional[Session] = None,
    ) -> None:
        self.base_url = base_url or ""
        self.headers = headers or {}
        self.auth = auth
        self.paginator = paginator
        # Default to the tracked session so every source built on top of
        # `RESTClient` participates in HTTP logging, metrics, and sample
        # capture. Callers can pass a pre-built `Session` for tests or
        # specialized auth (it should still be a tracked one in prod).
        self.session = session or make_tracked_session()
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
        resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None,
        initial_paginator_state: Optional[dict[str, Any]] = None,
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
            if initial_paginator_state is not None:
                paginator.set_resume_state(initial_paginator_state)
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

            if resume_hook is not None:
                resume_hook(paginator.get_resume_state() if paginator is not None and paginator.has_next_page else None)

            if paginator is None or not paginator.has_next_page:
                break

    @retry(
        retry=retry_if_exception_type(RESTClientRetryableError),
        stop=stop_after_attempt(5),
        wait=_retry_wait_seconds,
        reraise=True,
    )
    def _send_request(self, request: Request, hooks: Hooks) -> Response:
        prepared = self.session.prepare_request(request)
        response = self.session.send(prepared)

        if response.status_code == 429 or response.status_code >= 500:
            retry_after: Optional[float] = None
            retry_after_header = response.headers.get("Retry-After")
            if retry_after_header:
                try:
                    retry_after = min(float(retry_after_header), 300.0)
                except ValueError:
                    import datetime
                    from email.utils import parsedate_to_datetime

                    try:
                        dt = parsedate_to_datetime(retry_after_header)
                        retry_after = min(
                            max(0.0, (dt - datetime.datetime.now(datetime.UTC)).total_seconds()),
                            300.0,
                        )
                    except Exception:
                        pass
            raise RESTClientRetryableError(
                f"HTTP {response.status_code} for {response.url}",
                retry_after=retry_after,
            )

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
