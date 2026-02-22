"""
Tests for the WorkOS Radar integration.
"""

import pytest
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings

import requests
from parameterized import parameterized

from posthog.workos_radar import (
    WORKOS_RADAR_API_URL,
    WORKOS_RADAR_BYPASS_REDIS_KEY,
    RadarAction,
    RadarAuthMethod,
    RadarVerdict,
    SuspiciousAttemptBlocked,
    _call_radar_api,
    _get_raw_user_agent,
    _hash_email,
    _log_radar_event,
    add_radar_bypass_email,
    evaluate_auth_attempt,
    is_radar_bypass_email,
    remove_radar_bypass_email,
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

    @parameterized.expand(
        [
            ("blocked", True, False),
            ("bypassed", False, True),
            ("neither", False, False),
        ]
    )
    @patch("posthog.workos_radar.posthoganalytics.capture")
    def test_log_radar_event_records_was_blocked_and_was_bypassed(self, _name, was_blocked, was_bypassed, mock_capture):
        _log_radar_event(
            email="test@example.com",
            user_id=None,
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
            verdict=RadarVerdict.BLOCK,
            ip_address="1.2.3.4",
            user_agent="Chrome 135.0.0 on macOS 10.15",
            duration_ms=75.0,
            was_blocked=was_blocked,
            was_bypassed=was_bypassed,
        )

        props = mock_capture.call_args[1]["properties"]
        assert props["was_blocked"] == was_blocked
        assert props["was_bypassed"] == was_bypassed


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

    @parameterized.expand(
        [
            ("allow_not_blocked", RadarVerdict.ALLOW, False, False),
            ("challenge_not_blocked", RadarVerdict.CHALLENGE, False, False),
            ("error_not_blocked", RadarVerdict.ERROR, False, False),
        ]
    )
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_non_block_verdicts_do_not_raise_when_bypass_false(
        self, _name, verdict_value, expected_blocked, expected_bypassed, mock_call_api, mock_log_event
    ):
        mock_call_api.return_value = verdict_value
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        result = evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
            bypass=False,
        )

        assert result == verdict_value
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] == expected_blocked
        assert log_kwargs["was_bypassed"] == expected_bypassed

    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_block_verdict_raises_when_bypass_false(self, mock_call_api, mock_log_event):
        mock_call_api.return_value = RadarVerdict.BLOCK
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        with pytest.raises(SuspiciousAttemptBlocked):
            evaluate_auth_attempt(
                request=request,
                email="blocked@example.com",
                action=RadarAction.SIGNUP,
                auth_method=RadarAuthMethod.PASSWORD,
                bypass=False,
            )

        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] is True
        assert log_kwargs["was_bypassed"] is False

    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_block_verdict_does_not_raise_when_bypass_true(self, mock_call_api, mock_log_event):
        mock_call_api.return_value = RadarVerdict.BLOCK
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        verdict = evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
            bypass=True,
        )

        assert verdict == RadarVerdict.BLOCK
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] is False
        assert log_kwargs["was_bypassed"] is False

    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @patch("posthog.workos_radar.is_radar_bypass_email", return_value=True)
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_block_verdict_bypassed_for_whitelisted_email(self, mock_is_bypass, mock_call_api, mock_log_event):
        mock_call_api.return_value = RadarVerdict.BLOCK
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        verdict = evaluate_auth_attempt(
            request=request,
            email="bypassed@example.com",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
            bypass=False,
        )

        assert verdict == RadarVerdict.BLOCK
        mock_is_bypass.assert_called_once_with("bypassed@example.com")
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] is False
        assert log_kwargs["was_bypassed"] is True


class TestRadarBypassEmailRedis(TestCase):
    def setUp(self):
        from posthog.redis import get_client

        self.redis_client = get_client()
        self.redis_client.delete(WORKOS_RADAR_BYPASS_REDIS_KEY)

    def tearDown(self):
        self.redis_client.delete(WORKOS_RADAR_BYPASS_REDIS_KEY)

    def test_add_and_check_bypass_email(self):
        assert is_radar_bypass_email("test@example.com") is False
        add_radar_bypass_email("test@example.com")
        assert is_radar_bypass_email("test@example.com") is True

    def test_bypass_email_is_case_insensitive(self):
        add_radar_bypass_email("Test@Example.COM")
        assert is_radar_bypass_email("test@example.com") is True
        assert is_radar_bypass_email("TEST@EXAMPLE.COM") is True

    def test_remove_bypass_email(self):
        add_radar_bypass_email("test@example.com")
        assert is_radar_bypass_email("test@example.com") is True
        remove_radar_bypass_email("test@example.com")
        assert is_radar_bypass_email("test@example.com") is False

    def test_remove_nonexistent_email_is_noop(self):
        remove_radar_bypass_email("nonexistent@example.com")
        assert is_radar_bypass_email("nonexistent@example.com") is False


class TestRadarBypassViewSet(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from posthog.redis import get_client

        User = get_user_model()
        self.staff_user = User.objects.create_user(
            email="admin@posthog.com", password="testpass123!", is_staff=True, first_name="Admin"
        )
        self.non_staff_user = User.objects.create_user(
            email="user@posthog.com", password="testpass123!", is_staff=False, first_name="User"
        )
        self.redis_client = get_client()
        self.redis_client.delete(WORKOS_RADAR_BYPASS_REDIS_KEY)

    def tearDown(self):
        self.redis_client.delete(WORKOS_RADAR_BYPASS_REDIS_KEY)

    def test_non_staff_user_gets_403(self):
        self.client.force_login(self.non_staff_user)
        response = self.client.get("/api/admin/radar-bypass/")
        assert response.status_code == 403

    def test_list_bypass_emails(self):
        add_radar_bypass_email("a@example.com")
        add_radar_bypass_email("b@example.com")
        self.client.force_login(self.staff_user)
        response = self.client.get("/api/admin/radar-bypass/")
        assert response.status_code == 200
        assert sorted(response.json()) == ["a@example.com", "b@example.com"]

    def test_add_bypass_email(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            "/api/admin/radar-bypass/",
            {"email": "bypass@example.com"},
            content_type="application/json",
        )
        assert response.status_code == 201
        assert response.json() == {"email": "bypass@example.com"}
        assert is_radar_bypass_email("bypass@example.com") is True

    def test_add_invalid_email_returns_400(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            "/api/admin/radar-bypass/",
            {"email": "not-an-email"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert is_radar_bypass_email("not-an-email") is False

    def test_remove_bypass_email(self):
        add_radar_bypass_email("remove-me@example.com")
        self.client.force_login(self.staff_user)
        response = self.client.delete("/api/admin/radar-bypass/remove-me@example.com/")
        assert response.status_code == 204
        assert is_radar_bypass_email("remove-me@example.com") is False

    def test_list_empty(self):
        self.client.force_login(self.staff_user)
        response = self.client.get("/api/admin/radar-bypass/")
        assert response.status_code == 200
        assert response.json() == []
