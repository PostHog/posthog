from typing import Any

from slack_sdk import WebClient
from slack_sdk.http_retry import RetryHandler
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.state import RetryState

from posthog.egress.slack.observability import record_slack_api_exception, record_slack_api_response


class SlackObservabilityHandler(RetryHandler):
    def __init__(self, *, source: str, workspace_id: str | None, app_id: str) -> None:
        super().__init__()
        self._source = source
        self._workspace_id = workspace_id or None
        self._app_id = app_id

    def can_retry(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: HttpResponse | None = None,
        error: Exception | None = None,
    ) -> bool:
        endpoint = request.url.rsplit("/", 1)[-1]
        if response is not None:
            record_slack_api_response(
                response,
                source=self._source,
                workspace_id=self._workspace_id,
                app_id=self._app_id,
                method=request.method,
                endpoint=endpoint,
            )
        else:
            record_slack_api_exception(
                source=self._source,
                workspace_id=self._workspace_id,
                method=request.method,
                endpoint=endpoint,
            )
        return False


class SlackWebClient(WebClient):
    def __init__(
        self,
        token: str | None = None,
        *,
        source: str = "unknown",
        workspace_id: str | None = None,
        app_id: str = "unknown",
        **kwargs: Any,
    ) -> None:
        super().__init__(token=token, **kwargs)
        self.retry_handlers.insert(
            0,
            SlackObservabilityHandler(source=source, workspace_id=workspace_id, app_id=app_id),
        )
