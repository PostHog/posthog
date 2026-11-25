"""
Tests for the WorkOS Radar integration.
"""

import pytest
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

import requests
from parameterized import parameterized

from posthog.tasks.workos_radar import retry_countdown
from posthog.workos_radar import (
    WORKOS_RADAR_API_URL,
    WORKOS_RADAR_LOGIN_TIMEOUT,
    ChallengeRequired,
    RadarAction,
    RadarAttempt,
    RadarAuthMethod,
    RadarReportFailed,
    RadarVerdict,
    SuspiciousAttemptBlocked,
    _call_radar_api,
    _get_raw_user_agent,
    _hash_email,
    _is_sampled_for_login,
    _log_radar_event,
    _sample_key,
    evaluate_auth_attempt,
    send_attempt_success,
)


class TestRadarHelpers(SimpleTestCase):
    def test_hash_email_produces_consistent_hash(self):
        email = "test@example.com"
        hash1 = _hash_email(email)
        hash2 = _hash_email(email)
        assert hash1 == hash2
        assert len(hash1) == 16

    def test_hash_email_is_case_insensitive(self):
        assert _hash_email("Test@Example.Com") == _hash_email("test@example.com")

    @parameterized.expand(
        [
            ("browser", {"HTTP_USER_AGENT": "Mozilla/5.0 TestBrowser"}, "Mozilla/5.0 TestBrowser"),
            ("missing_header", {}, "unknown"),
            ("oversized_header", {"HTTP_USER_AGENT": "a" * 5000}, "a" * 1024),
        ]
    )
    def test_get_raw_user_agent(self, _name, headers, expected):
        assert _get_raw_user_agent(RequestFactory().get("/", **headers)) == expected


@override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
class TestAttemptSuccessReport(SimpleTestCase):
    @parameterized.expand(
        [
            ("success", "radar_att_01ABC", False, 200, 1, None),
            ("completed_challenge", "radar_att_01ABC", True, 200, 1, None),
            ("refused_is_not_retried", "radar_att_01ABC", False, 404, 1, None),
            ("rate_limited_is_retried", "radar_att_01ABC", False, 429, 1, RadarReportFailed),
            ("server_error_is_retried", "radar_att_01ABC", False, 503, 1, RadarReportFailed),
            ("id_that_is_not_a_path_segment", "../users", False, 200, 0, None),
            ("no_id", "", False, 200, 0, None),
        ]
    )
    @patch("posthog.workos_radar.requests.put")
    def test_send_attempt_success(
        self, _name, attempt_id, challenge_completed, status_code, expected_calls, expected_error, mock_put
    ):
        mock_put.return_value.status_code = status_code
        mock_put.return_value.ok = status_code < 400

        if expected_error:
            with pytest.raises(expected_error):
                send_attempt_success(attempt_id, challenge_completed)
        else:
            send_attempt_success(attempt_id, challenge_completed)

        assert mock_put.call_count == expected_calls
        if expected_calls:
            assert mock_put.call_args[0][0] == f"{WORKOS_RADAR_API_URL}/{attempt_id}"
            assert mock_put.call_args[1]["headers"]["Authorization"] == "Bearer test_key"
            expected_body = {"attempt_status": "success"}
            if challenge_completed:
                expected_body["challenge_status"] = "success"
            assert mock_put.call_args[1]["json"] == expected_body


class TestAttemptSuccessRetry(SimpleTestCase):
    @parameterized.expand(
        [
            ("seconds", "30", 30),
            ("over_the_limit", "86400", 3600),
            ("http_date", "Wed, 21 Oct 2026 07:28:00 GMT", None),
            ("missing", None, None),
        ]
    )
    @patch("posthog.workos_radar.requests.put")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_a_throttled_report_carries_the_retry_after_delay(self, _name, header, expected, mock_put):
        mock_put.return_value.status_code = 429
        mock_put.return_value.headers = {"Retry-After": header} if header else {}

        with pytest.raises(RadarReportFailed) as error:
            send_attempt_success("radar_att_01ABC")

        assert error.value.retry_after == expected

    @parameterized.expand(
        [
            ("first_retry", 0, None, 60),
            ("fourth_retry", 3, None, 480),
            ("capped", 5, None, 900),
            ("retry_after_wins", 0, 30, 30),
        ]
    )
    def test_retry_countdown(self, _name, retries, retry_after, expected):
        assert retry_countdown(retries, retry_after) == expected


class TestLoginSample(SimpleTestCase):
    def test_sample_is_stable_per_address_and_close_to_the_percentage(self):
        emails = [f"user{i}@example.com" for i in range(2000)]

        with patch("posthog.workos_radar.get_instance_setting", return_value=30):
            sampled = [email for email in emails if _is_sampled_for_login(_sample_key(email, None))]
            assert all(_is_sampled_for_login(_sample_key(f" {email.upper()} ", None)) for email in sampled)

        assert 0.25 < len(sampled) / len(emails) < 0.35

    def test_an_existing_account_is_sampled_by_its_id_whatever_the_spelling(self):
        spellings = ["iiii@example.com", "\u0130iii@example.com", "IIII@EXAMPLE.COM"]

        assert {_sample_key(email, "account-1") for email in spellings} == {"account-1"}


class TestRadarApiCall(SimpleTestCase):
    @patch("posthog.workos_radar.requests.post")
    @override_settings(WORKOS_RADAR_API_KEY="test_api_key")
    def test_call_radar_api_allow_verdict(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"verdict": "allow", "attempt_id": "radar_att_01ABC"}
        mock_post.return_value = mock_response

        verdict = _call_radar_api(
            email="test@example.com",
            ip_address="1.2.3.4",
            user_agent="TestBrowser",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict == RadarAttempt(verdict=RadarVerdict.ALLOW, attempt_id="radar_att_01ABC")
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == WORKOS_RADAR_API_URL
        assert "Bearer test_api_key" in str(call_args[1]["headers"])
        assert call_args[1]["json"]["action"] == "sign-in"

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

        assert verdict.verdict == RadarVerdict.CHALLENGE

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

        assert verdict.verdict == RadarVerdict.BLOCK

    @parameterized.expand(
        [
            ("rejected_token_is_retried_without_it", 400, 2),
            ("rate_limit_is_not_retried", 429, 1),
            ("server_error_is_not_retried", 500, 1),
        ]
    )
    @patch("posthog.workos_radar.requests.post")
    @override_settings(WORKOS_RADAR_API_KEY="test_api_key")
    def test_call_radar_api_with_a_signals_token(self, _name, first_status, expected_calls, mock_post):
        first_response = MagicMock(status_code=first_status, text="error")
        retry_response = MagicMock(status_code=200)
        retry_response.json.return_value = {"verdict": "block"}
        mock_post.side_effect = [first_response, retry_response]

        verdict = _call_radar_api(
            email="test@example.com",
            ip_address="1.2.3.4",
            user_agent="TestBrowser",
            action=RadarAction.SIGNIN,
            auth_method=RadarAuthMethod.PASSWORD,
            signals_id="signals_123",
        )

        assert mock_post.call_count == expected_calls
        assert mock_post.call_args_list[0][1]["json"]["signals_id"] == "signals_123"
        if expected_calls == 2:
            assert "signals_id" not in mock_post.call_args_list[1][1]["json"]
            assert verdict.verdict == RadarVerdict.BLOCK
        else:
            assert verdict.verdict == RadarVerdict.ERROR

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

        assert verdict.verdict == RadarVerdict.ERROR

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

        assert verdict.verdict == RadarVerdict.ERROR

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

        assert verdict.verdict == RadarVerdict.ERROR


class TestRadarEventLogging(SimpleTestCase):
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
            bypass_source="rule" if was_bypassed else None,
        )

        props = mock_capture.call_args[1]["properties"]
        assert props["was_blocked"] == was_blocked
        assert props["was_bypassed"] == was_bypassed
        assert props["bypass_source"] == ("rule" if was_bypassed else None)


class TestEvaluateAuthAttempt(SimpleTestCase):
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
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.ALLOW)

        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        verdict = evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
            user_id="user_123",
        )

        assert verdict is not None
        assert verdict.verdict == RadarVerdict.ALLOW
        mock_call_api.assert_called_once()
        mock_log_event.assert_called_once()

        log_call_args = mock_log_event.call_args
        assert log_call_args[1]["email"] == "test@example.com"
        assert log_call_args[1]["user_id"] == "user_123"
        assert log_call_args[1]["action"] == RadarAction.SIGNUP
        assert log_call_args[1]["auth_method"] == RadarAuthMethod.PASSWORD
        assert log_call_args[1]["verdict"] == RadarVerdict.ALLOW
        assert "duration_ms" in log_call_args[1]
        assert isinstance(log_call_args[1]["duration_ms"], float)

    @parameterized.expand(
        [
            ("allow_not_blocked", RadarVerdict.ALLOW),
            ("error_not_blocked", RadarVerdict.ERROR),
        ]
    )
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_non_block_verdicts_do_not_raise(self, _name, verdict_value, mock_call_api, mock_log_event):
        mock_call_api.return_value = RadarAttempt(verdict=verdict_value)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        result = evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert result is not None
        assert result.verdict == verdict_value
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] is False
        assert log_kwargs["was_bypassed"] is False

    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_block_verdict_raises(self, mock_call_api, mock_log_event):
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.BLOCK)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        with pytest.raises(SuspiciousAttemptBlocked):
            evaluate_auth_attempt(
                request=request,
                email="blocked@example.com",
                action=RadarAction.SIGNUP,
                auth_method=RadarAuthMethod.PASSWORD,
            )

        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] is True
        assert log_kwargs["was_bypassed"] is False

    @parameterized.expand(
        [
            # (name, mode, sample percent, auth method, verdict, expect call, expect raise, logged mode)
            ("mode_off_skips_radar", "off", 100, RadarAuthMethod.PASSWORD, RadarVerdict.BLOCK, False, False, None),
            (
                "unknown_mode_reads_as_off",
                "loud",
                100,
                RadarAuthMethod.PASSWORD,
                RadarVerdict.BLOCK,
                False,
                False,
                None,
            ),
            (
                "address_outside_sample_skips",
                "enforce",
                0,
                RadarAuthMethod.PASSWORD,
                RadarVerdict.BLOCK,
                False,
                False,
                None,
            ),
            ("passkey_login_skips", "enforce", 100, RadarAuthMethod.PASSKEY, RadarVerdict.BLOCK, False, False, None),
            (
                "shadow_records_block_without_refusing",
                "shadow",
                100,
                RadarAuthMethod.PASSWORD,
                RadarVerdict.BLOCK,
                True,
                False,
                "shadow",
            ),
            (
                "enforce_refuses_block",
                "enforce",
                100,
                RadarAuthMethod.PASSWORD,
                RadarVerdict.BLOCK,
                True,
                True,
                "enforce",
            ),
            (
                "enforce_lets_challenge_through_without_a_form",
                "enforce",
                100,
                RadarAuthMethod.PASSWORD,
                RadarVerdict.CHALLENGE,
                True,
                False,
                "enforce",
            ),
        ]
    )
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_signin_follows_the_login_mode(
        self,
        _name,
        mode,
        sample_percent,
        auth_method,
        verdict,
        expect_call,
        expect_raise,
        logged_mode,
        mock_call_api,
        mock_log_event,
    ):
        mock_call_api.return_value = RadarAttempt(verdict=verdict)
        request = RequestFactory().post("/api/login", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")
        instance_settings = {"WORKOS_RADAR_LOGIN_MODE": mode, "WORKOS_RADAR_LOGIN_SAMPLE_PERCENT": sample_percent}

        with patch("posthog.workos_radar.get_instance_setting", side_effect=instance_settings.__getitem__):
            if expect_raise:
                with pytest.raises(SuspiciousAttemptBlocked):
                    self._evaluate_signin(request, auth_method)
            else:
                self._evaluate_signin(request, auth_method)

        assert mock_call_api.called is expect_call
        if expect_call:
            assert mock_call_api.call_args[1]["timeout"] == WORKOS_RADAR_LOGIN_TIMEOUT
        if logged_mode is not None:
            log_kwargs = mock_log_event.call_args[1]
            assert log_kwargs["mode"] == logged_mode
            assert log_kwargs["was_blocked"] is expect_raise
        else:
            mock_log_event.assert_not_called()

    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_signin_skips_radar_when_the_settings_cannot_be_read(self, mock_call_api):
        request = RequestFactory().post("/api/login", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        with patch("posthog.workos_radar.get_instance_setting", side_effect=RuntimeError("database unavailable")):
            assert self._evaluate_signin(request, RadarAuthMethod.PASSWORD) is None

        mock_call_api.assert_not_called()

    @parameterized.expand(
        [
            ("valid_token_is_sent", "signals_01ABCdef-2.3:4", "signals_01ABCdef-2.3:4"),
            ("token_with_spaces_is_dropped", "signals 01", ""),
            ("oversized_token_is_dropped", "a" * 513, ""),
        ]
    )
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api", return_value=RadarAttempt(verdict=RadarVerdict.ALLOW))
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_signals_token_reaches_radar_only_in_the_expected_shape(
        self, _name, sent, expected, mock_call_api, mock_log_event
    ):
        request = RequestFactory().post("/api/login", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
            signals_id=sent,
        )

        assert mock_call_api.call_args[1]["signals_id"] == expected
        assert mock_log_event.call_args[1]["signals_sent"] is bool(expected)

    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api", return_value=RadarAttempt(verdict=RadarVerdict.BLOCK))
    @patch("posthog.workos_radar.is_signup_risk_exempt", return_value=True)
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_signup_exemption_does_not_cover_a_login(self, mock_is_exempt, mock_call_api, mock_log_event):
        request = RequestFactory().post("/api/login", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")
        instance_settings = {"WORKOS_RADAR_LOGIN_MODE": "enforce", "WORKOS_RADAR_LOGIN_SAMPLE_PERCENT": 100}

        with patch("posthog.workos_radar.get_instance_setting", side_effect=instance_settings.__getitem__):
            with pytest.raises(SuspiciousAttemptBlocked):
                self._evaluate_signin(request, RadarAuthMethod.PASSWORD)

        mock_is_exempt.assert_not_called()

    @parameterized.expand(
        [
            ("deployment_without_forwarding", False, "", "198.51.100.42", "8.8.8.8"),
            ("forged_entry_behind_a_trusted_proxy", True, "10.0.0.2", "10.0.0.2", "8.8.8.8, 198.51.100.42"),
        ]
    )
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api", return_value=RadarAttempt(verdict=RadarVerdict.ALLOW))
    def test_a_forwarded_ip_the_deployment_does_not_trust_never_reaches_radar(
        self, _name, use_forwarded, trusted_proxies, remote_addr, forwarded_for, mock_call_api, mock_log_event
    ):
        request = RequestFactory().post(
            "/api/signup", REMOTE_ADDR=remote_addr, HTTP_X_FORWARDED_FOR=forwarded_for, HTTP_USER_AGENT="TestBrowser"
        )

        with self.settings(
            WORKOS_RADAR_ENABLED=True,
            WORKOS_RADAR_API_KEY="test_key",
            USE_X_FORWARDED_HOST=use_forwarded,
            TRUST_ALL_PROXIES=False,
            TRUSTED_PROXIES=trusted_proxies,
        ):
            evaluate_auth_attempt(
                request=request,
                email="test@example.com",
                action=RadarAction.SIGNUP,
                auth_method=RadarAuthMethod.PASSWORD,
            )

        assert mock_call_api.call_args[1]["ip_address"] == "198.51.100.42"

    def _evaluate_signin(self, request, auth_method):
        return evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNIN,
            auth_method=auth_method,
            challenge_allowed=False,
        )

    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @patch("posthog.workos_radar.is_signup_risk_exempt", return_value=True)
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_block_verdict_bypassed_for_exempt_email(self, mock_is_bypass, mock_call_api, mock_log_event):
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.BLOCK)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        verdict = evaluate_auth_attempt(
            request=request,
            email="bypassed@example.com",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert verdict is not None
        assert verdict.verdict == RadarVerdict.BLOCK
        mock_is_bypass.assert_called_once_with("bypassed@example.com")
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] is False
        assert log_kwargs["was_bypassed"] is True
        assert log_kwargs["bypass_source"] == "rule"


class TestChallengeFlow(TestCase):
    @patch("posthog.workos_radar.create_challenge_nonce", return_value="challenge:abc123:uuid")
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(
        WORKOS_RADAR_ENABLED=True,
        WORKOS_RADAR_API_KEY="test_key",
        CLOUDFLARE_TURNSTILE_SITE_KEY="site_key_123",
    )
    def test_challenge_verdict_raises_challenge_required_without_token(
        self, mock_call_api, mock_log_event, mock_create_nonce
    ):
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.CHALLENGE, attempt_id="radar_att_01ABC")
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        with pytest.raises(ChallengeRequired) as exc_info:
            evaluate_auth_attempt(
                request=request,
                email="test@example.com",
                action=RadarAction.SIGNUP,
                auth_method=RadarAuthMethod.PASSWORD,
            )

        assert exc_info.value.status_code == 428
        assert exc_info.value.extra["challenge_nonce"] == "challenge:abc123:uuid"
        assert exc_info.value.extra["turnstile_site_key"] == "site_key_123"
        mock_create_nonce.assert_called_once_with("test@example.com", "1.2.3.4", radar_attempt_id="radar_att_01ABC")

        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_challenged"] is True
        assert log_kwargs["was_challenge_completed"] is False

    @patch("posthog.workos_radar.verify_turnstile_token", return_value=True)
    @patch("posthog.workos_radar.consume_challenge_nonce", return_value="radar_att_01ABC")
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_challenge_verdict_allows_with_valid_turnstile_token(
        self, mock_call_api, mock_log_event, mock_consume_nonce, mock_verify_token
    ):
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.CHALLENGE)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        result = evaluate_auth_attempt(
            request=request,
            email="test@example.com",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
            turnstile_token="valid_token",
            challenge_nonce="challenge:abc123:uuid",
        )

        assert result == RadarAttempt(
            verdict=RadarVerdict.CHALLENGE, attempt_id="radar_att_01ABC", challenge_completed=True
        )
        mock_call_api.assert_not_called()
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_challenged"] is False
        assert log_kwargs["was_challenge_completed"] is True

    @patch("posthog.workos_radar.verify_turnstile_token", return_value=False)
    @patch("posthog.workos_radar.consume_challenge_nonce", return_value="radar_att_01ABC")
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_challenge_verdict_blocks_with_invalid_turnstile_token(
        self, mock_call_api, mock_log_event, mock_consume_nonce, mock_verify_token
    ):
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.CHALLENGE)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        with pytest.raises(SuspiciousAttemptBlocked):
            evaluate_auth_attempt(
                request=request,
                email="test@example.com",
                action=RadarAction.SIGNUP,
                auth_method=RadarAuthMethod.PASSWORD,
                turnstile_token="bad_token",
                challenge_nonce="challenge:abc123:uuid",
            )

        mock_call_api.assert_not_called()
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] is True

    @patch("posthog.workos_radar.verify_turnstile_token")
    @patch("posthog.workos_radar.consume_challenge_nonce", return_value=None)
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_challenge_verdict_blocks_with_invalid_nonce(
        self, mock_call_api, mock_log_event, mock_consume_nonce, mock_verify_token
    ):
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.CHALLENGE)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        with pytest.raises(SuspiciousAttemptBlocked):
            evaluate_auth_attempt(
                request=request,
                email="test@example.com",
                action=RadarAction.SIGNUP,
                auth_method=RadarAuthMethod.PASSWORD,
                turnstile_token="valid_token",
                challenge_nonce="challenge:bad:nonce",
            )

        mock_call_api.assert_not_called()
        mock_verify_token.assert_not_called()

    @patch("posthog.workos_radar.verify_turnstile_token", return_value=True)
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_challenge_verdict_blocks_with_expired_nonce_despite_valid_token(
        self, mock_call_api, mock_log_event, mock_verify_token
    ):
        from posthog.turnstile import create_challenge_nonce

        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.CHALLENGE)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        nonce = create_challenge_nonce("test@example.com", "1.2.3.4")

        from posthog.redis import get_client

        get_client().delete(f"turnstile_nonce:{nonce}")

        with pytest.raises(SuspiciousAttemptBlocked):
            evaluate_auth_attempt(
                request=request,
                email="test@example.com",
                action=RadarAction.SIGNUP,
                auth_method=RadarAuthMethod.PASSWORD,
                turnstile_token="valid_token",
                challenge_nonce=nonce,
            )

        mock_call_api.assert_not_called()
        mock_verify_token.assert_not_called()
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_blocked"] is True

    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key", CLOUDFLARE_TURNSTILE_SITE_KEY="")
    def test_challenge_verdict_blocks_when_turnstile_not_configured(self, mock_call_api, mock_log_event):
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.CHALLENGE)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        with pytest.raises(SuspiciousAttemptBlocked):
            evaluate_auth_attempt(
                request=request,
                email="test@example.com",
                action=RadarAction.SIGNUP,
                auth_method=RadarAuthMethod.PASSWORD,
            )

    @patch("posthog.workos_radar.is_signup_risk_exempt", return_value=True)
    @patch("posthog.workos_radar._log_radar_event")
    @patch("posthog.workos_radar._call_radar_api")
    @override_settings(WORKOS_RADAR_ENABLED=True, WORKOS_RADAR_API_KEY="test_key")
    def test_challenge_verdict_bypassed_for_exempt_email(self, mock_call_api, mock_log_event, mock_is_bypass):
        mock_call_api.return_value = RadarAttempt(verdict=RadarVerdict.CHALLENGE)
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4", HTTP_USER_AGENT="TestBrowser")

        result = evaluate_auth_attempt(
            request=request,
            email="bypassed@example.com",
            action=RadarAction.SIGNUP,
            auth_method=RadarAuthMethod.PASSWORD,
        )

        assert result is not None
        assert result.verdict == RadarVerdict.CHALLENGE
        log_kwargs = mock_log_event.call_args[1]
        assert log_kwargs["was_bypassed"] is True
        assert log_kwargs["bypass_source"] == "rule"
        assert log_kwargs["was_challenged"] is False
