"""
Tests for the WorkOS Radar integration.
"""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings

import requests

from posthog.workos_radar import (
    WORKOS_RADAR_API_URL,
    RadarAction,
    RadarAuthMethod,
    RadarVerdict,
    _call_radar_api,
    _get_raw_user_agent,
    _hash_email,
    _log_radar_event,
    evaluate_auth_attempt,
)


class TestRadarHelpers(TestCase):
    def test_hash_email_produces_consistent_hash(self):
        email = "test@example.com"
        hash1 = _hash_email(email)
        hash2 = _hash_email(email)
        assert hash1 == hash2
        assert len(hash1) == 16

    def test_hash_email_is_case_insensitive(self):
        assert _hash_email("Test@Example.Com") == _hash_email("test@example.com")

    def test_get_raw_user_agent(self):
        factory = RequestFactory()
        request = factory.get("/", HTTP_USER_AGENT="Mozilla/5.0 TestBrowser")
        assert _get_raw_user_agent(request) == "Mozilla/5.0 TestBrowser"


class TestRadarApiCall(TestCase):
    @patch("posthog.workos_radar.requests.post")
    @override_settings(WORKOS_RADAR_API_KEY="test_api_key")
    def test_call_radar_api_allow_verdict(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"verdict": "allow"}
        mock_post.return_value = mock_response

        verdict = _call_radar_api(
            email="test@example.com",
            ip_address="1.2.3.4",
            user_agent="TestBrowser",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict == RadarVerdict.ALLOW
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == WORKOS_RADAR_API_URL
        assert "Bearer test_api_key" in str(call_args[1]["headers"])

    @patch("posthog.workos_radar.requests.post")
    @override_settings(WORKOS_RADAR_API_KEY="test_api_key")
    def test_call_radar_api_challenge_verdict(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"verdict": "challenge"}
        mock_post.return_value = mock_response

        verdict = _call_radar_api(
            email="test@example.com",
            ip_address="1.2.3.4",
            user_agent="TestBrowser",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict == RadarVerdict.CHALLENGE

    @patch("posthog.workos_radar.requests.post")
    @override_settings(WORKOS_RADAR_API_KEY="test_api_key")
    def test_call_radar_api_block_verdict(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"verdict": "block"}
        mock_post.return_value = mock_response

        verdict = _call_radar_api(
            email="test@example.com",
            ip_address="1.2.3.4",
            user_agent="TestBrowser",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict == RadarVerdict.BLOCK

    @patch("posthog.workos_radar.requests.post")
    @override_settings(WORKOS_RADAR_API_KEY="test_api_key")
    def test_call_radar_api_handles_api_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        verdict = _call_radar_api(
            email="test@example.com",
            ip_address="1.2.3.4",
            user_agent="TestBrowser",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict == RadarVerdict.ERROR

    @patch("posthog.workos_radar.requests.post")
    @override_settings(WORKOS_RADAR_API_KEY="test_api_key")
    def test_call_radar_api_handles_timeout(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("timeout")

        verdict = _call_radar_api(
            email="test@example.com",
            ip_address="1.2.3.4",
            user_agent="TestBrowser",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict == RadarVerdict.ERROR

    @patch("posthog.workos_radar.requests.post")
    @override_settings(WORKOS_RADAR_API_KEY="test_api_key")
    def test_call_radar_api_handles_exception(self, mock_post):
        mock_post.side_effect = Exception("unexpected error")

        verdict = _call_radar_api(
            email="test@example.com",
            ip_address="1.2.3.4",
            user_agent="TestBrowser",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict == RadarVerdict.ERROR


class TestRadarEventLogging(TestCase):
    @patch("posthog.workos_radar.posthoganalytics.capture")
    def test_log_radar_event_captures_posthog_event(self, mock_capture):
        _log_radar_event(
            email="test@example.com",
            user_id="user_123",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
            verdict=RadarVerdict.ALLOW,
            ip_address="1.2.3.4",
            user_agent="Chrome 135.0.0 on macOS 10.15",
            duration_ms=123.45,
        )

        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        assert call_args[1]["distinct_id"] == "user_123"
        assert call_args[1]["event"] == "workos_radar_attempt"
        props = call_args[1]["properties"]
        assert props["action"] == "login"
        assert props["auth_method"] == "Password"
        assert props["verdict"] == "allow"
        assert props["would_challenge"] is False
        assert props["would_block"] is False
        assert props["radar_api_duration_ms"] == 123.45

    @patch("posthog.workos_radar.posthoganalytics.capture")
    def test_log_radar_event_with_challenge_verdict(self, mock_capture):
        _log_radar_event(
            email="test@example.com",
            user_id=None,
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSKEY,
            verdict=RadarVerdict.CHALLENGE,
            ip_address="1.2.3.4",
            user_agent="Chrome 135.0.0 on macOS 10.15",
            duration_ms=50.0,
        )

        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        assert "pre_signup_" in call_args[1]["distinct_id"]
        props = call_args[1]["properties"]
        assert props["would_challenge"] is True
        assert props["would_block"] is False

    @patch("posthog.workos_radar.posthoganalytics.capture")
    def test_log_radar_event_with_block_verdict(self, mock_capture):
        _log_radar_event(
            email="test@example.com",
            user_id=None,
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
            verdict=RadarVerdict.BLOCK,
            ip_address="1.2.3.4",
            user_agent="Chrome 135.0.0 on macOS 10.15",
            duration_ms=75.0,
        )

        mock_capture.assert_called_once()
        props = mock_capture.call_args[1]["properties"]
        assert props["would_challenge"] is False
        assert props["would_block"] is True


class TestEvaluateAuthAttempt(TestCase):
    @override_settings(WORKOS_RADAR_ENABLED=False)
    def test_returns_none_when_radar_disabled(self):
        factory = RequestFactory()
        request = factory.get("/")

        verdict = evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict is None

    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="")
    def test_returns_none_when_no_api_key(self):
        factory = RequestFactory()
        request = factory.get("/")

        verdict = evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict is None

    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_calls_api_and_logs_event_when_enabled(self, mock_call_api, mock_log_event):
        mock_call_api.return_value = RadarVerdict.ALLOW

        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        verdict = evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
            user_id="user_123",
        )

        assert verdict == RadarVerdict.ALLOW
        mock_call_api.assert_called_once()
        mock_log_event.assert_called_once()

        log_call_args = mock_log_event.call_args
        assert log_call_args[1]["email"] == "test@example.com"
        assert log_call_args[1]["user_id"] == "user_123"
        assert log_call_args[1]["action"] == RadarAction.SIGNIN
        assert log_call_args[1]["auth_method"] == RadarAuthMethod.PASSWORD
        assert log_call_args[1]["verdict"] == RadarVerdict.ALLOW
        assert "duration_ms" in log_call_args[1]
        assert isinstance(log_call_args[1]["duration_ms"], float)
