from typing import Any

from slack_sdk import WebClient
from slack_sdk.http_retry import RetryHandler
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.state import RetryState

from posthog.egress.slack.observability import record_slack_attempt


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
        record_slack_attempt(
            source=self._source,
            workspace_id=self._workspace_id,
            app_id=self._app_id,
            request=request,
            response=response,
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
