from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings


@override_settings(
    ELEVENLABS_API_KEY="test-key",
    ELEVENLABS_API_BASE_URL="https://api.elevenlabs.example",
)
class TestMaxHandsFreeAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The viewset gates on the max-hands-free feature flag server-side; force it on
        # so tests exercise the endpoint logic rather than the entitlement check.
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _token_url(self) -> str:
        return f"/api/environments/{self.team.id}/max_hands_free/token/"

    @patch("ee.api.hands_free.requests.post")
    def test_token_returns_signed_token_from_elevenlabs(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"token": "single-use-token-abc"}),
        )

        response = self.client.post(self._token_url(), format="json")

        assert response.status_code == 200
        assert response.json() == {"token": "single-use-token-abc"}
        assert mock_post.call_args.args[0].endswith("/v1/single-use-token/realtime_scribe")
        assert mock_post.call_args.kwargs["headers"]["xi-api-key"] == "test-key"

    @override_settings(ELEVENLABS_API_KEY="")
    def test_returns_503_when_api_key_missing(self) -> None:
        response = self.client.post(self._token_url(), format="json")
        assert response.status_code == 503

    @patch("ee.api.hands_free.requests.post")
    def test_returns_502_when_provider_errors(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=429, text="rate limited")
        response = self.client.post(self._token_url(), format="json")
        assert response.status_code == 502

    @patch("ee.api.hands_free.requests.post")
    def test_returns_502_when_provider_returns_empty_token(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"token": ""}))
        response = self.client.post(self._token_url(), format="json")
        assert response.status_code == 502

    @patch("ee.api.hands_free.requests.post")
    def test_provider_error_does_not_log_response_body(self, mock_post: MagicMock) -> None:
        upstream = MagicMock(status_code=500, text="ECHOED API KEY OR PII")
        mock_post.return_value = upstream

        with patch("ee.api.hands_free.logger") as mock_logger:
            response = self.client.post(self._token_url(), format="json")

        assert response.status_code == 502
        log_calls = mock_logger.warning.call_args_list + mock_logger.exception.call_args_list
        for call in log_calls:
            for value in list(call.args) + list(call.kwargs.values()):
                assert "ECHOED API KEY OR PII" not in str(value)

    def test_requires_authentication(self) -> None:
        self.client.logout()
        response = self.client.post(self._token_url(), format="json")
        assert response.status_code in (401, 403)

    def _synthesize_url(self) -> str:
        return f"/api/environments/{self.team.id}/max_hands_free/synthesize/"

    @patch("ee.api.hands_free.requests.post")
    def test_synthesize_streams_audio_from_elevenlabs(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            status_code=200,
            iter_content=MagicMock(return_value=iter([b"mp3-chunk-1", b"mp3-chunk-2"])),
        )

        response = self.client.post(self._synthesize_url(), data={"text": "hello"}, format="json")

        assert response.status_code == 200
        assert response["Content-Type"] == "audio/mpeg"
        assert response["Cache-Control"] == "no-store"
        assert b"".join(response.streaming_content) == b"mp3-chunk-1mp3-chunk-2"  # type: ignore[attr-defined]
        mock_post.return_value.close.assert_called_once()

    def test_synthesize_rejects_text_over_limit(self) -> None:
        response = self.client.post(
            self._synthesize_url(),
            data={"text": "x" * 2001},
            format="json",
        )
        assert response.status_code == 400

    def test_synthesize_rejects_empty_text(self) -> None:
        response = self.client.post(self._synthesize_url(), data={"text": ""}, format="json")
        assert response.status_code == 400

    @patch("ee.api.hands_free.requests.post")
    def test_synthesize_502_when_provider_errors(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=429, text="quota exceeded")
        response = self.client.post(self._synthesize_url(), data={"text": "hello"}, format="json")
        assert response.status_code == 502
        mock_post.return_value.close.assert_called_once()

    @override_settings(ELEVENLABS_API_KEY="")
    def test_synthesize_503_when_api_key_missing(self) -> None:
        response = self.client.post(self._synthesize_url(), data={"text": "hello"}, format="json")
        assert response.status_code == 503

    def test_endpoints_403_when_feature_flag_disabled_for_org(self) -> None:
        # Stop the class-level patch so the real PostHogFeatureFlagPermission runs against
        # an org that doesn't have the flag enabled — expect 403, no upstream calls.
        self._ff_patcher.stop()
        with patch("posthoganalytics.feature_enabled", return_value=False):
            token_response = self.client.post(self._token_url(), format="json")
            synth_response = self.client.post(self._synthesize_url(), data={"text": "hello"}, format="json")
        # Restart so addCleanup doesn't double-stop.
        self._ff_patcher.start()
        assert token_response.status_code == 403
        assert synth_response.status_code == 403

    def test_synthesize_requires_authentication(self) -> None:
        self.client.logout()
        response = self.client.post(self._synthesize_url(), data={"text": "hello"}, format="json")
        assert response.status_code in (401, 403)

    @patch("posthog.api.streaming.StreamingHttpResponse")
    @patch("ee.api.hands_free.requests.post")
    def test_synthesize_closes_upstream_when_response_construction_fails(
        self, mock_post: MagicMock, mock_streaming_response: MagicMock
    ) -> None:
        # Upstream returns 200 (so close isn't called on the error-status path) but the
        # StreamingHttpResponse constructor blows up before we can return. Without the
        # try/except in synthesize the upstream connection would leak — Django would
        # surface a 500 to the client and the requests connection would only release on
        # GC of the unconsumed iter_content generator.
        upstream = MagicMock(status_code=200)
        mock_post.return_value = upstream
        mock_streaming_response.side_effect = RuntimeError("django blew up")

        response = self.client.post(self._synthesize_url(), data={"text": "hello"}, format="json")

        assert response.status_code == 500
        upstream.close.assert_called_once()
