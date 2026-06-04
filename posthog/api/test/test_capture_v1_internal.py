from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from requests.adapters import HTTPAdapter

from posthog.api.capture_v1 import (
    CaptureV1InternalError,
    CaptureV1Result,
    _build_v1_headers,
    _normalize_options_and_properties,
    _parse_retry_after,
    capture_v1_batch_internal,
    capture_v1_internal,
    prepare_capture_v1_batch,
)
from posthog.settings.ingestion import CAPTURE_INTERNAL_URL, CAPTURE_V1_INTERNAL_ENDPOINT

EXPECTED_URL = f"{CAPTURE_INTERNAL_URL}{CAPTURE_V1_INTERNAL_ENDPOINT}"


class MockResponse:
    """Lightweight mock for requests.Response with configurable body and headers."""

    def __init__(
        self,
        status_code: int = 200,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        text: str = "",
    ):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = text or (str(body) if body else "")

    def json(self) -> dict[str, Any]:
        if self._body is None:
            raise ValueError("no json body")
        return self._body


class InstallV1Spy:
    """Spy that records POST calls and returns a configurable sequence of responses."""

    def __init__(self, mock_session_fn: MagicMock, responses: list[MockResponse] | None = None):
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses or [MockResponse(body={})])
        self._call_idx = 0

        def spy_post(url: str, **kwargs: Any) -> MockResponse:
            self.calls.append({"url": url, **kwargs})
            resp = self._responses[min(self._call_idx, len(self._responses) - 1)]
            self._call_idx += 1
            return resp

        mock_session = MagicMock()
        mock_session.post.side_effect = spy_post
        mock_session.mount = MagicMock()
        mock_session_fn.return_value.__enter__.return_value = mock_session
        self._mock_session = mock_session


def _ok_results(*uuids: str) -> dict[str, Any]:
    return {"results": {uid: {"result": "ok"} for uid in uuids}}


def _make_event(
    event: str = "test_event",
    distinct_id: str = "user-1",
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {"event": event, "distinct_id": distinct_id}
    out.update(extra)
    return out


class TestBuildV1Headers(SimpleTestCase):
    def test_all_required_headers_present(self) -> None:
        headers = _build_v1_headers("phc_test123", attempt=1)
        assert headers["Authorization"] == "Bearer phc_test123"
        assert headers["Content-Type"] == "application/json"
        assert "posthog-capture-v1-internal" in headers["User-Agent"]
        assert headers["PostHog-Sdk-Info"] == "posthog-capture-v1-internal/1.0"
        assert headers["PostHog-Attempt"] == "1"
        assert len(headers["PostHog-Request-Id"]) == 36
        assert "T" in headers["PostHog-Request-Timestamp"]

    def test_attempt_increments(self) -> None:
        h1 = _build_v1_headers("tok", attempt=1)
        h2 = _build_v1_headers("tok", attempt=3)
        assert h1["PostHog-Attempt"] == "1"
        assert h2["PostHog-Attempt"] == "3"

    def test_request_id_unique_per_call(self) -> None:
        h1 = _build_v1_headers("tok", attempt=1)
        h2 = _build_v1_headers("tok", attempt=1)
        assert h1["PostHog-Request-Id"] != h2["PostHog-Request-Id"]


class TestNormalizeOptionsAndProperties(SimpleTestCase):
    def test_typed_options_propagated(self) -> None:
        ev: dict[str, Any] = {
            "options": {"cookieless_mode": True, "disable_skew_correction": True, "product_tour_id": "tour-1"},
            "properties": {"some_prop": "val"},
        }
        options, sid, wid, props = _normalize_options_and_properties(
            ev, process_person_profile=True, event_source="test"
        )
        assert options["cookieless_mode"] is True
        assert options["disable_skew_correction"] is True
        assert options["product_tour_id"] == "tour-1"
        assert "process_person_profile" not in options
        assert sid is None
        assert wid is None
        assert props == {"some_prop": "val"}

    def test_legacy_properties_lifted_and_stripped(self) -> None:
        ev: dict[str, Any] = {
            "properties": {
                "$cookieless_mode": True,
                "$ignore_sent_at": True,
                "$product_tour_id": "tour-2",
                "$process_person_profile": True,
                "$session_id": "sess-1",
                "$window_id": "win-1",
                "keep_me": 42,
            },
        }
        options, sid, wid, props = _normalize_options_and_properties(
            ev, process_person_profile=True, event_source="test"
        )
        assert options["cookieless_mode"] is True
        assert options["disable_skew_correction"] is True
        assert options["product_tour_id"] == "tour-2"
        assert sid == "sess-1"
        assert wid == "win-1"
        assert "$cookieless_mode" not in props
        assert "$ignore_sent_at" not in props
        assert "$product_tour_id" not in props
        assert "$process_person_profile" not in props
        assert "$session_id" not in props
        assert "$window_id" not in props
        assert props["keep_me"] == 42

    def test_legacy_alias_disable_skew_adjustment_stripped(self) -> None:
        ev: dict[str, Any] = {
            "properties": {"disable_skew_adjustment": True, "other": 1},
        }
        options, _, _, props = _normalize_options_and_properties(ev, process_person_profile=True, event_source="test")
        assert options["disable_skew_correction"] is True
        assert "disable_skew_adjustment" not in props

    def test_explicit_wins_over_legacy_on_conflict(self) -> None:
        ev: dict[str, Any] = {
            "options": {"cookieless_mode": False},
            "session_id": "explicit-sess",
            "properties": {"$cookieless_mode": True, "$session_id": "legacy-sess"},
        }
        options, sid, _, props = _normalize_options_and_properties(ev, process_person_profile=True, event_source="test")
        assert options["cookieless_mode"] is False
        assert sid == "explicit-sess"
        assert "$cookieless_mode" not in props
        assert "$session_id" not in props

    def test_unknown_option_key_raises(self) -> None:
        ev: dict[str, Any] = {"options": {"bogus_key": True}, "properties": {}}
        with self.assertRaises(CaptureV1InternalError) as ctx:
            _normalize_options_and_properties(ev, process_person_profile=True, event_source="test")
        assert "unknown option key" in str(ctx.exception)

    def test_process_person_profile_false_forces_option(self) -> None:
        ev: dict[str, Any] = {"properties": {}}
        options, _, _, _ = _normalize_options_and_properties(ev, process_person_profile=False, event_source="test")
        assert options["process_person_profile"] is False

    def test_process_person_profile_true_leaves_unset(self) -> None:
        ev: dict[str, Any] = {"properties": {}}
        options, _, _, _ = _normalize_options_and_properties(ev, process_person_profile=True, event_source="test")
        assert "process_person_profile" not in options

    def test_no_options_when_all_empty_and_ppp_true(self) -> None:
        ev: dict[str, Any] = {"properties": {"keep": 1}}
        options, sid, wid, props = _normalize_options_and_properties(
            ev, process_person_profile=True, event_source="test"
        )
        assert options == {}
        assert sid is None
        assert wid is None
        assert props == {"keep": 1}

    def test_caller_input_not_mutated(self) -> None:
        original_props = {"$session_id": "s1", "keep": 1}
        ev: dict[str, Any] = {"properties": original_props}
        _normalize_options_and_properties(ev, process_person_profile=False, event_source="test")
        assert "$session_id" in original_props


class TestPrepareCaptureV1Batch(SimpleTestCase):
    def test_envelope_shape(self) -> None:
        events = [_make_event()]
        payload, uuids = prepare_capture_v1_batch(events, token="tok", event_source="test")
        assert payload["capture_internal"] is True
        assert payload["historical_migration"] is False
        assert "created_at" in payload
        assert len(payload["batch"]) == 1
        assert len(uuids) == 1
        assert payload["batch"][0]["uuid"] == uuids[0]

    def test_uuid_generated_when_absent(self) -> None:
        events = [_make_event()]
        payload, uuids = prepare_capture_v1_batch(events, token="tok", event_source="test")
        assert len(uuids[0]) == 36
        assert payload["batch"][0]["uuid"] == uuids[0]

    def test_uuid_preserved_when_present(self) -> None:
        uid = str(uuid4())
        events = [_make_event(event_uuid=uid)]
        payload, uuids = prepare_capture_v1_batch(events, token="tok", event_source="test")
        assert uuids[0] == uid
        assert payload["batch"][0]["uuid"] == uid

    def test_options_omitted_when_empty(self) -> None:
        events = [_make_event()]
        payload, _ = prepare_capture_v1_batch(events, token="tok", event_source="test", process_person_profile=True)
        assert "options" not in payload["batch"][0]

    def test_options_present_when_set(self) -> None:
        events = [_make_event(options={"cookieless_mode": True})]
        payload, _ = prepare_capture_v1_batch(events, token="tok", event_source="test")
        assert payload["batch"][0]["options"]["cookieless_mode"] is True

    def test_session_window_as_top_level_fields(self) -> None:
        events = [_make_event(session_id="s1", window_id="w1")]
        payload, _ = prepare_capture_v1_batch(events, token="tok", event_source="test")
        entry = payload["batch"][0]
        assert entry["session_id"] == "s1"
        assert entry["window_id"] == "w1"
        assert "$session_id" not in entry.get("properties", {})
        assert "$window_id" not in entry.get("properties", {})

    def test_distinct_id_fallback_from_properties(self) -> None:
        events = [{"event": "e", "properties": {"distinct_id": "from_props"}}]
        payload, _ = prepare_capture_v1_batch(events, token="tok", event_source="test")
        assert payload["batch"][0]["distinct_id"] == "from_props"

    def test_timestamp_defaults_to_now(self) -> None:
        events = [_make_event()]
        before = datetime.now(UTC).isoformat()
        payload, _ = prepare_capture_v1_batch(events, token="tok", event_source="test")
        after = datetime.now(UTC).isoformat()
        ts = payload["batch"][0]["timestamp"]
        assert before <= ts <= after

    @parameterized.expand(
        [
            ("empty_token", "", "tok_required"),
            ("no_events", None, "at_least_one"),
        ]
    )
    def test_validation_errors(self, _name: str, token: str | None, fragment: str) -> None:
        events = [_make_event()] if token is not None else []
        tok = token if token is not None else "tok"
        with self.assertRaises(CaptureV1InternalError) as ctx:
            prepare_capture_v1_batch(events if events else [], token=tok if tok else "", event_source="src")
        assert any(w in str(ctx.exception).lower() for w in fragment.lower().split("_"))

    def test_missing_event_name_raises(self) -> None:
        events = [{"distinct_id": "u1", "properties": {}}]
        with self.assertRaises(CaptureV1InternalError) as ctx:
            prepare_capture_v1_batch(events, token="tok", event_source="src")
        assert "event name" in str(ctx.exception).lower()

    def test_missing_distinct_id_raises(self) -> None:
        events = [{"event": "e", "properties": {}}]
        with self.assertRaises(CaptureV1InternalError) as ctx:
            prepare_capture_v1_batch(events, token="tok", event_source="src")
        assert "distinct_id" in str(ctx.exception).lower()

    @parameterized.expand(
        [
            ("$snapshot",),
            ("$performance_event",),
            ("$snapshot_items",),
        ]
    )
    def test_replay_event_names_rejected(self, event_name: str) -> None:
        events = [_make_event(event=event_name)]
        with self.assertRaises(CaptureV1InternalError) as ctx:
            prepare_capture_v1_batch(events, token="tok", event_source="src")
        assert "replay event" in str(ctx.exception).lower()

    def test_legacy_properties_stripped_in_batch(self) -> None:
        events = [
            _make_event(
                properties={
                    "$cookieless_mode": True,
                    "$ignore_sent_at": False,
                    "$product_tour_id": "t",
                    "$process_person_profile": True,
                    "$session_id": "s1",
                    "$window_id": "w1",
                    "keep": 1,
                }
            )
        ]
        payload, _ = prepare_capture_v1_batch(events, token="tok", event_source="test")
        entry = payload["batch"][0]
        props = entry["properties"]
        for key in (
            "$cookieless_mode",
            "$ignore_sent_at",
            "$product_tour_id",
            "$process_person_profile",
            "$session_id",
            "$window_id",
        ):
            assert key not in props, f"{key} should have been stripped"
        assert props["keep"] == 1
        assert entry["session_id"] == "s1"
        assert entry["window_id"] == "w1"
        assert entry["options"]["cookieless_mode"] is True


class TestCaptureV1BatchInternal(SimpleTestCase):
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_happy_path_batch(self, mock_session_fn: MagicMock) -> None:
        uid1, uid2 = str(uuid4()), str(uuid4())
        events = [
            _make_event(event_uuid=uid1),
            _make_event(event="other", distinct_id="u2", event_uuid=uid2),
        ]
        spy = InstallV1Spy(mock_session_fn, [MockResponse(body=_ok_results(uid1, uid2))])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="happy")

        assert result.status_code == 200
        assert result.succeeded()
        assert set(result.ok) == {uid1, uid2}
        assert not result.dropped
        assert not result.warnings
        assert not result.retried
        assert result.error is None

        assert len(spy.calls) == 1
        assert spy.calls[0]["url"] == EXPECTED_URL

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_headers_on_initial_request(self, mock_session_fn: MagicMock) -> None:
        uid = str(uuid4())
        events = [_make_event(event_uuid=uid)]
        spy = InstallV1Spy(mock_session_fn, [MockResponse(body=_ok_results(uid))])

        capture_v1_batch_internal(events=events, token="phc_abc", event_source="hdr")

        headers = spy.calls[0]["headers"]
        assert headers["Authorization"] == "Bearer phc_abc"
        assert headers["Content-Type"] == "application/json"
        assert headers["PostHog-Sdk-Info"] == "posthog-capture-v1-internal/1.0"
        assert headers["PostHog-Attempt"] == "1"
        assert len(headers["PostHog-Request-Id"]) == 36
        assert "T" in headers["PostHog-Request-Timestamp"]

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_envelope_shape_on_wire(self, mock_session_fn: MagicMock) -> None:
        uid = str(uuid4())
        events = [_make_event(event_uuid=uid)]
        spy = InstallV1Spy(mock_session_fn, [MockResponse(body=_ok_results(uid))])

        capture_v1_batch_internal(events=events, token="tok", event_source="env")

        body = spy.calls[0]["json"]
        assert body["capture_internal"] is True
        assert body["historical_migration"] is False
        assert "created_at" in body
        assert len(body["batch"]) == 1
        assert body["batch"][0]["uuid"] == uid

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_options_propagated_to_wire(self, mock_session_fn: MagicMock) -> None:
        uid = str(uuid4())
        events = [
            _make_event(
                event_uuid=uid,
                options={"cookieless_mode": True, "disable_skew_correction": True, "product_tour_id": "t1"},
                session_id="s1",
                window_id="w1",
            )
        ]
        spy = InstallV1Spy(mock_session_fn, [MockResponse(body=_ok_results(uid))])

        capture_v1_batch_internal(events=events, token="tok", event_source="opt")

        entry = spy.calls[0]["json"]["batch"][0]
        assert entry["options"]["cookieless_mode"] is True
        assert entry["options"]["disable_skew_correction"] is True
        assert entry["options"]["product_tour_id"] == "t1"
        assert entry["session_id"] == "s1"
        assert entry["window_id"] == "w1"
        assert "$cookieless_mode" not in entry["properties"]
        assert "$session_id" not in entry["properties"]

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_options_omitted_when_none_set_and_ppp_true(self, mock_session_fn: MagicMock) -> None:
        uid = str(uuid4())
        events = [_make_event(event_uuid=uid)]
        spy = InstallV1Spy(mock_session_fn, [MockResponse(body=_ok_results(uid))])

        capture_v1_batch_internal(events=events, token="tok", event_source="nopt", process_person_profile=True)

        entry = spy.calls[0]["json"]["batch"][0]
        assert "options" not in entry

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_process_person_profile_false(self, mock_session_fn: MagicMock) -> None:
        uid = str(uuid4())
        events = [_make_event(event_uuid=uid)]
        spy = InstallV1Spy(mock_session_fn, [MockResponse(body=_ok_results(uid))])

        capture_v1_batch_internal(events=events, token="tok", event_source="ppp")

        entry = spy.calls[0]["json"]["batch"][0]
        assert entry["options"]["process_person_profile"] is False
        assert "$process_person_profile" not in entry["properties"]

    @parameterized.expand(
        [
            # non-retryable
            ("400_validation", 400, {"error": "invalid_request", "error_description": "bad"}),
            ("401_auth", 401, {"error": "unauthorized", "error_description": "bad token"}),
            ("402_billing", 402, {"error": "billing_limit", "error_description": "quota"}),
            ("413_too_large", 413, {"error": "too_large", "error_description": "payload"}),
            ("415_media", 415, {"error": "unsupported_media", "error_description": "type"}),
            # retryable (Retry-After emitted by capture-rs)
            ("408_timeout", 408, {"error": "request_timeout", "error_description": "timeout"}),
            ("500_internal", 500, {"error": "internal_error", "error_description": "boom"}),
            ("502_bad_gateway", 502, {"error": "bad_gateway", "error_description": "upstream"}),
            ("503_unavailable", 503, {"error": "service_unavailable", "error_description": "down"}),
            ("504_gateway_timeout", 504, {"error": "gateway_timeout", "error_description": "slow"}),
        ]
    )
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_whole_request_failures(
        self,
        _name: str,
        status: int,
        error_body: dict[str, str],
        mock_session_fn: MagicMock,
    ) -> None:
        events = [_make_event()]
        InstallV1Spy(mock_session_fn, [MockResponse(status_code=status, body=error_body)])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="fail")

        assert result.status_code == status
        assert result.error is not None
        assert result.error["error"] == error_body["error"]
        assert not result.succeeded()

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_partial_failure_mixed_results(self, mock_session_fn: MagicMock) -> None:
        u_ok, u_drop, u_warn = str(uuid4()), str(uuid4()), str(uuid4())
        events = [
            _make_event(event_uuid=u_ok),
            _make_event(event_uuid=u_drop, event="drop_me"),
            _make_event(event_uuid=u_warn, event="warn_me"),
        ]
        body: dict[str, Any] = {
            "results": {
                u_ok: {"result": "ok"},
                u_drop: {"result": "drop", "details": "quota"},
                u_warn: {"result": "warning", "details": "sdk old"},
            }
        }
        InstallV1Spy(mock_session_fn, [MockResponse(body=body)])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="partial")

        assert result.status_code == 200
        assert u_ok in result.ok
        assert u_drop in result.dropped
        assert u_warn in result.warnings
        assert not result.retried
        assert not result.succeeded()

    @patch("posthog.api.capture_v1.time.sleep")
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_auto_resubmit_retry_events(self, mock_session_fn: MagicMock, mock_sleep: MagicMock) -> None:
        u_ok, u_retry = str(uuid4()), str(uuid4())
        events = [
            _make_event(event_uuid=u_ok),
            _make_event(event_uuid=u_retry, event="retryable"),
        ]
        first_response = MockResponse(
            body={
                "results": {
                    u_ok: {"result": "ok"},
                    u_retry: {"result": "retry", "details": "busy"},
                }
            },
            headers={"Retry-After": "2"},
        )
        second_response = MockResponse(
            body={"results": {u_retry: {"result": "ok"}}},
        )
        spy = InstallV1Spy(mock_session_fn, [first_response, second_response])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="resub")

        assert result.status_code == 200
        assert result.succeeded()
        assert set(result.ok) == {u_ok, u_retry}
        assert not result.retried

        assert len(spy.calls) == 2
        mock_sleep.assert_called_once_with(2.0)

        # Second request should have incremented attempt and only retry uuid.
        second_headers = spy.calls[1]["headers"]
        assert second_headers["PostHog-Attempt"] == "2"
        assert second_headers["PostHog-Request-Id"] != spy.calls[0]["headers"]["PostHog-Request-Id"]
        second_batch = spy.calls[1]["json"]["batch"]
        assert len(second_batch) == 1
        assert second_batch[0]["uuid"] == u_retry

    @patch("posthog.api.capture_v1.time.sleep")
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_bounded_retries_exhausted(self, mock_session_fn: MagicMock, mock_sleep: MagicMock) -> None:
        u_retry = str(uuid4())
        events = [_make_event(event_uuid=u_retry)]
        persistent_retry = MockResponse(
            body={"results": {u_retry: {"result": "retry"}}},
            headers={"Retry-After": "1"},
        )
        InstallV1Spy(mock_session_fn, [persistent_retry, persistent_retry, persistent_retry])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="bounded", max_retries=2)

        assert result.status_code == 200
        assert u_retry in result.retried
        assert not result.succeeded()

    @patch("posthog.api.capture_v1.time.sleep")
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_retry_after_capped(self, mock_session_fn: MagicMock, mock_sleep: MagicMock) -> None:
        u_retry = str(uuid4())
        events = [_make_event(event_uuid=u_retry)]
        resp1 = MockResponse(
            body={"results": {u_retry: {"result": "retry"}}},
            headers={"Retry-After": "9999"},
        )
        resp2 = MockResponse(body=_ok_results(u_retry))
        InstallV1Spy(mock_session_fn, [resp1, resp2])

        capture_v1_batch_internal(events=events, token="tok", event_source="cap")

        mock_sleep.assert_called_once_with(5.0)

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_headers_on_resubmit(self, mock_session_fn: MagicMock) -> None:
        u_retry = str(uuid4())
        events = [_make_event(event_uuid=u_retry)]
        resp1 = MockResponse(
            body={"results": {u_retry: {"result": "retry"}}},
            headers={"Retry-After": "0"},
        )
        resp2 = MockResponse(body=_ok_results(u_retry))
        spy = InstallV1Spy(mock_session_fn, [resp1, resp2])

        with patch("posthog.api.capture_v1.time.sleep"):
            capture_v1_batch_internal(events=events, token="tok", event_source="rh")

        h1 = spy.calls[0]["headers"]
        h2 = spy.calls[1]["headers"]
        assert h1["PostHog-Attempt"] == "1"
        assert h2["PostHog-Attempt"] == "2"
        assert h1["PostHog-Request-Id"] != h2["PostHog-Request-Id"]
        for h in (h1, h2):
            assert "Authorization" in h
            assert "PostHog-Sdk-Info" in h
            assert "PostHog-Request-Timestamp" in h

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_transport_retry_adapter_mounted(self, mock_session_fn: MagicMock) -> None:
        uid = str(uuid4())
        events = [_make_event(event_uuid=uid)]
        spy = InstallV1Spy(mock_session_fn, [MockResponse(body=_ok_results(uid))])

        capture_v1_batch_internal(events=events, token="tok", event_source="mount")

        spy._mock_session.mount.assert_called_once()
        args = spy._mock_session.mount.call_args
        assert args[0][0] == EXPECTED_URL
        adapter = args[0][1]
        assert isinstance(adapter, HTTPAdapter)

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_all_drop_batch(self, mock_session_fn: MagicMock) -> None:
        u1, u2 = str(uuid4()), str(uuid4())
        events = [_make_event(event_uuid=u1), _make_event(event_uuid=u2)]
        body: dict[str, Any] = {
            "results": {
                u1: {"result": "drop", "details": "quota"},
                u2: {"result": "drop", "details": "restricted"},
            }
        }
        InstallV1Spy(mock_session_fn, [MockResponse(body=body)])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="alldrop")

        assert result.status_code == 200
        assert not result.succeeded()
        assert set(result.dropped) == {u1, u2}
        assert not result.ok
        assert not result.retried

    @patch("posthog.api.capture_v1.time.sleep")
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_mixed_retry_drop_warn_resubmits_only_retry(
        self, mock_session_fn: MagicMock, mock_sleep: MagicMock
    ) -> None:
        u_drop, u_warn, u_retry = str(uuid4()), str(uuid4()), str(uuid4())
        events = [
            _make_event(event_uuid=u_drop),
            _make_event(event_uuid=u_warn),
            _make_event(event_uuid=u_retry),
        ]
        first_resp = MockResponse(
            body={
                "results": {
                    u_drop: {"result": "drop"},
                    u_warn: {"result": "warning"},
                    u_retry: {"result": "retry"},
                }
            },
            headers={"Retry-After": "0"},
        )
        second_resp = MockResponse(body={"results": {u_retry: {"result": "ok"}}})
        spy = InstallV1Spy(mock_session_fn, [first_resp, second_resp])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="mix")

        assert len(spy.calls) == 2
        assert u_drop in result.dropped
        assert u_warn in result.warnings
        assert u_retry in result.ok
        assert not result.retried

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_empty_results_map(self, mock_session_fn: MagicMock) -> None:
        uid = str(uuid4())
        events = [_make_event(event_uuid=uid)]
        InstallV1Spy(mock_session_fn, [MockResponse(body={"results": {}})])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="empty")

        assert result.status_code == 200
        assert not result.ok
        assert not result.dropped
        assert not result.retried

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_non_json_200_body(self, mock_session_fn: MagicMock) -> None:
        events = [_make_event()]
        InstallV1Spy(mock_session_fn, [MockResponse(status_code=200, body=None, text="not json")])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="badjson")

        assert result.status_code == 200
        assert result.error is not None
        assert result.error["error"] == "invalid_json"
        assert not result.succeeded()

    @patch("posthog.api.capture_v1.time.sleep")
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_retry_without_retry_after_header(self, mock_session_fn: MagicMock, mock_sleep: MagicMock) -> None:
        u_retry = str(uuid4())
        events = [_make_event(event_uuid=u_retry)]
        resp1 = MockResponse(
            body={"results": {u_retry: {"result": "retry"}}},
        )
        resp2 = MockResponse(body=_ok_results(u_retry))
        InstallV1Spy(mock_session_fn, [resp1, resp2])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="noheader")

        assert result.succeeded()
        mock_sleep.assert_not_called()

    @patch("posthog.api.capture_v1.time.sleep")
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_resubmit_preserves_envelope_metadata(self, mock_session_fn: MagicMock, mock_sleep: MagicMock) -> None:
        u_retry = str(uuid4())
        events = [_make_event(event_uuid=u_retry)]
        resp1 = MockResponse(
            body={"results": {u_retry: {"result": "retry"}}},
            headers={"Retry-After": "0"},
        )
        resp2 = MockResponse(body=_ok_results(u_retry))
        spy = InstallV1Spy(mock_session_fn, [resp1, resp2])

        capture_v1_batch_internal(
            events=events,
            token="tok",
            event_source="envelope",
            historical_migration=True,
        )

        body1 = spy.calls[0]["json"]
        body2 = spy.calls[1]["json"]
        assert body2["capture_internal"] is True
        assert body2["historical_migration"] is True
        assert body2["created_at"] == body1["created_at"]

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_max_retries_one_means_no_resubmit(self, mock_session_fn: MagicMock) -> None:
        u_retry = str(uuid4())
        events = [_make_event(event_uuid=u_retry)]
        resp = MockResponse(
            body={"results": {u_retry: {"result": "retry"}}},
            headers={"Retry-After": "0"},
        )
        spy = InstallV1Spy(mock_session_fn, [resp])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="noretry", max_retries=1)

        assert len(spy.calls) == 1
        assert u_retry in result.retried
        assert not result.succeeded()

    @patch("posthog.api.capture_v1.time.sleep")
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_drop_round1_retry_ok_round2_merged(self, mock_session_fn: MagicMock, mock_sleep: MagicMock) -> None:
        u_drop, u_retry = str(uuid4()), str(uuid4())
        events = [
            _make_event(event_uuid=u_drop),
            _make_event(event_uuid=u_retry),
        ]
        resp1 = MockResponse(
            body={
                "results": {
                    u_drop: {"result": "drop", "details": "quota"},
                    u_retry: {"result": "retry"},
                }
            },
            headers={"Retry-After": "0"},
        )
        resp2 = MockResponse(body={"results": {u_retry: {"result": "ok"}}})
        InstallV1Spy(mock_session_fn, [resp1, resp2])

        result = capture_v1_batch_internal(events=events, token="tok", event_source="merge")

        assert u_drop in result.dropped
        assert u_retry in result.ok
        assert not result.retried
        assert result.results[u_drop]["result"] == "drop"
        assert result.results[u_retry]["result"] == "ok"


class TestParseRetryAfter(SimpleTestCase):
    @parameterized.expand(
        [
            ("none", None, 0.0),
            ("empty_string", "", 0.0),
            ("zero", "0", 0.0),
            ("positive", "2", 2.0),
            ("float_value", "1.5", 1.5),
            ("capped", "9999", 5.0),
            ("negative_clamped", "-1", 0.0),
            ("non_numeric_fallback", "garbage", 1.0),
        ]
    )
    def test_parse_retry_after(self, _name: str, header: str | None, expected: float) -> None:
        assert _parse_retry_after(header) == expected


class TestCaptureV1Internal(SimpleTestCase):
    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_single_event_wrapper(self, mock_session_fn: MagicMock) -> None:
        uid = str(uuid4())
        spy = InstallV1Spy(mock_session_fn, [MockResponse(body=_ok_results(uid))])

        result = capture_v1_internal(
            token="tok",
            event_name="single_test",
            event_source="single",
            distinct_id="u1",
            event_uuid=uid,
            session_id="s1",
            window_id="w1",
            options={"cookieless_mode": True},
            properties={"custom": "val"},
        )

        assert result.status_code == 200
        assert uid in result.ok

        entry = spy.calls[0]["json"]["batch"][0]
        assert entry["event"] == "single_test"
        assert entry["distinct_id"] == "u1"
        assert entry["uuid"] == uid
        assert entry["session_id"] == "s1"
        assert entry["window_id"] == "w1"
        assert entry["options"]["cookieless_mode"] is True
        assert entry["properties"]["custom"] == "val"

    @patch("posthog.api.capture_v1.internal_requests_session")
    def test_single_minimal(self, mock_session_fn: MagicMock) -> None:
        InstallV1Spy(mock_session_fn, [MockResponse(body={"results": {}})])

        result = capture_v1_internal(
            token="tok",
            event_name="minimal",
            event_source="min",
            distinct_id="u1",
        )
        assert result.status_code == 200


class TestCaptureV1Result(SimpleTestCase):
    def test_succeeded_true(self) -> None:
        r = CaptureV1Result(status_code=200, ok=["a", "b"])
        assert r.succeeded()

    def test_succeeded_false_on_error(self) -> None:
        r = CaptureV1Result(status_code=400, error={"error": "bad"})
        assert not r.succeeded()

    def test_succeeded_false_on_drops(self) -> None:
        r = CaptureV1Result(status_code=200, dropped=["a"])
        assert not r.succeeded()

    def test_succeeded_false_on_retried(self) -> None:
        r = CaptureV1Result(status_code=200, retried=["a"])
        assert not r.succeeded()

    def test_terminal_failures(self) -> None:
        r = CaptureV1Result(
            status_code=200,
            results={"a": {"result": "drop"}, "b": {"result": "retry"}},
            dropped=["a"],
            retried=["b"],
        )
        failures = r.terminal_failures()
        assert "a" in failures
        assert "b" in failures

    def test_raise_for_status_on_error(self) -> None:
        r = CaptureV1Result(status_code=503, error={"error": "server_error", "error_description": "down"})
        with self.assertRaises(CaptureV1InternalError):
            r.raise_for_status()

    def test_raise_for_status_on_partial_failure(self) -> None:
        r = CaptureV1Result(status_code=200, dropped=["a"])
        with self.assertRaises(CaptureV1InternalError):
            r.raise_for_status()

    def test_raise_for_status_noop_on_success(self) -> None:
        r = CaptureV1Result(status_code=200, ok=["a"])
        r.raise_for_status()
