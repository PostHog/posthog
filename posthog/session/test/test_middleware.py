from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory

from posthog.session.middleware import UserAuthSessionActivityMiddleware


class TestUserAuthSessionActivityMiddleware(BaseTest):
    def _make_middleware(self, response):
        return UserAuthSessionActivityMiddleware(lambda r: response)

    def _authed_request(self):
        request = RequestFactory().get("/")
        request.user = self.user
        session = MagicMock()
        session.__contains__ = MagicMock(return_value=True)
        request.session = session
        return request

    def test_syncs_metadata_for_normal_responses(self):
        response = HttpResponse("ok")
        middleware = self._make_middleware(response)
        with patch("posthog.session.middleware.sync_current_session_metadata") as mock_sync:
            middleware(self._authed_request())
        mock_sync.assert_called_once()

    def test_skips_metadata_sync_for_streaming_responses(self):
        # Regression: streaming responses must not open a DB connection in the response phase.
        # sync_current_session_metadata uses transaction.on_commit which runs immediately in
        # autocommit mode, opening a new connection that stays pinned for the stream lifetime.
        response = StreamingHttpResponse(iter([b"data: hello\n\n"]))
        middleware = self._make_middleware(response)
        with patch("posthog.session.middleware.sync_current_session_metadata") as mock_sync:
            middleware(self._authed_request())
        mock_sync.assert_not_called()
