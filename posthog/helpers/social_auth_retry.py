"""Retry the OAuth provider calls of a login after a transient egress failure.

Without the retry, one shed connection to the provider ends the login attempt.

The retry installs on `social_core.backends.base.BaseAuth.request`, the one call that every OAuth
backend makes, and not on a subclass for each provider. A session records the dotted path of the
class that signed the person in, so a new backend class would sign out everyone who holds a session
that the old path opened.
"""

from functools import wraps
from typing import Any

import requests
import structlog
from social_core.backends.base import BaseAuth
from social_core.exceptions import AuthConnectionError
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_random

logger = structlog.get_logger(__name__)

# A 429 is what the egress proxy answers with when it sheds a call. The provider never ran the
# request, so a replay cannot spend the authorization code a second time.
RETRY_STATUS_CODES = frozenset({429})

_INSTALLED_MARKER = "_posthog_social_auth_retry"


def _is_transient(error: BaseException) -> bool:
    # `BaseAuth.request` wraps every `requests.ConnectionError`, the proxy ones included, into an
    # `AuthConnectionError`.
    if isinstance(error, AuthConnectionError):
        return True
    response = getattr(error, "response", None)
    return isinstance(response, requests.Response) and response.status_code in RETRY_STATUS_CODES


def _log_retry(state: RetryCallState) -> None:
    # The retried call takes the backend as its first argument.
    backend = state.args[0] if state.args else None
    logger.warning(
        "social_auth_provider_request_retry",
        backend=getattr(backend, "name", None),
        attempt=state.attempt_number,
        error=type(state.outcome.exception()).__name__ if state.outcome else None,
    )


def install() -> None:
    if getattr(BaseAuth.request, _INSTALLED_MARKER, False):
        return

    original_request = BaseAuth.request

    @wraps(original_request)
    @retry(
        stop=stop_after_attempt(3),
        # A login holds a web worker while it waits, so each wait is short. The spread stops a burst
        # of blocked logins from replaying together.
        wait=wait_random(0.1, 0.4),
        retry=retry_if_exception(_is_transient),
        before_sleep=_log_retry,
        reraise=True,
    )
    def request_with_retry(self: BaseAuth, *args: Any, **kwargs: Any) -> requests.Response:
        return original_request(self, *args, **kwargs)

    setattr(request_with_retry, _INSTALLED_MARKER, True)
    BaseAuth.request = request_with_retry  # type: ignore[method-assign]
