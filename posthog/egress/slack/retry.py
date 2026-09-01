"""Retry transient Slack Web API server errors.

Slack signals a transient server-side failure as an HTTP 200 body with ``ok: false`` and one of
the codes below, not as an HTTP 5xx. So the built-in server-error handler (which keys on 5xx)
never sees it, and a single blip turns a whole channel or member listing into a dead end. These
handlers retry any such response a few times with backoff before the error escapes to the caller.

The handlers attach to the shared ``SlackWebClient``, so they retry every Slack Web API call that
returns one of these codes, not only the listing calls that motivated them. Slack documents that
``internal_error`` and ``fatal_error`` can follow a partial success, so a retried non-idempotent
write such as ``chat.postMessage`` can post twice. The SDK's built-in connection-error handler
already retries every method on a dropped connection, so this widens that behavior rather than
introducing it.
"""

from slack_sdk.http_retry import RetryHandler
from slack_sdk.http_retry.async_handler import AsyncRetryHandler
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.state import RetryState

# Slack error codes that mean "try the same request again", not "this install is broken".
# Kept separate from the auth-failure codes, which are terminal and must not be retried.
SLACK_TRANSIENT_ERROR_CODES = frozenset({"internal_error", "service_unavailable", "fatal_error", "request_timeout"})

# Two retries (three attempts) with backoff: enough to ride out a brief Slack blip without
# stretching a request-path listing call by more than a few seconds when Slack stays down.
SLACK_TRANSIENT_MAX_RETRY_COUNT = 2


def _is_transient_slack_error(response: HttpResponse | None) -> bool:
    if response is None or not response.body:
        return False
    return response.body.get("ok") is False and response.body.get("error") in SLACK_TRANSIENT_ERROR_CODES


class SlackTransientErrorRetryHandler(RetryHandler):
    def __init__(self) -> None:
        super().__init__(max_retry_count=SLACK_TRANSIENT_MAX_RETRY_COUNT)

    def _can_retry(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: HttpResponse | None = None,
        error: Exception | None = None,
    ) -> bool:
        return _is_transient_slack_error(response)


class SlackTransientErrorAsyncRetryHandler(AsyncRetryHandler):
    def __init__(self) -> None:
        super().__init__(max_retry_count=SLACK_TRANSIENT_MAX_RETRY_COUNT)

    async def _can_retry_async(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: HttpResponse | None = None,
        error: Exception | None = None,
    ) -> bool:
        return _is_transient_slack_error(response)
