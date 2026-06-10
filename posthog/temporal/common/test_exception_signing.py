import hmac
import json
import hashlib

import pytest

from posthog.temporal.common.exception_signing import (
    ATTESTATION_PROPERTY,
    MAX_MESSAGE_LENGTH,
    SIGNATURE_PROPERTY,
    build_attestation,
    make_exception_signer,
    serialize_attestation,
    sign,
)

SECRET = "test-secret-0123456789abcdef"
CAPTURED_AT = "2026-06-10T12:00:00+00:00"


def _exception_event(properties: dict | None = None) -> dict:
    props = {
        "$exception_list": [
            {
                "type": "HTTPError",
                "value": "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/charges",
                "stacktrace": {
                    "frames": [
                        {"module": "requests.models", "filename": "requests/models.py", "in_app": False},
                        {
                            "module": "posthog.temporal.data_imports.sources.stripe.source",
                            "filename": "posthog/temporal/data_imports/sources/stripe/source.py",
                            "in_app": True,
                        },
                    ]
                },
            }
        ],
        "team_id": 12345,
        "run_id": "0196f1a2-1111-7000-8000-0123456789ab",
        "source_id": "0196f1a2-3333-7000-8000-0123456789ab",
        "schema_id": "0196f1a2-4444-7000-8000-0123456789ab",
        "temporal.workflow.run_id": "11111111-2222-4333-8444-555555555555",
    }
    if properties:
        props.update(properties)
    return {"event": "$exception", "timestamp": CAPTURED_AT, "properties": props}


class TestBuildAttestation:
    def test_extracts_content_and_job_context(self):
        att = build_attestation(_exception_event()["properties"], captured_at=CAPTURED_AT)
        assert att == {
            "v": 1,
            "exception_type": "HTTPError",
            "message": "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/charges",
            "top_frame": "posthog/temporal/data_imports/sources/stripe/source.py",
            "captured_at": CAPTURED_AT,
            "team_id": 12345,
            "run_id": "0196f1a2-1111-7000-8000-0123456789ab",
            "source_id": "0196f1a2-3333-7000-8000-0123456789ab",
            "schema_id": "0196f1a2-4444-7000-8000-0123456789ab",
            "workflow_run_id": "11111111-2222-4333-8444-555555555555",
        }

    def test_prefers_first_in_app_frame_over_first_frame(self):
        att = build_attestation(_exception_event()["properties"], captured_at=CAPTURED_AT)
        assert att["top_frame"] == "posthog/temporal/data_imports/sources/stripe/source.py"

    def test_falls_back_to_first_frame_when_no_in_app(self):
        props = _exception_event()["properties"]
        for frame in props["$exception_list"][0]["stacktrace"]["frames"]:
            frame["in_app"] = False
        att = build_attestation(props, captured_at=CAPTURED_AT)
        assert att["top_frame"] == "requests/models.py"

    def test_truncates_long_message(self):
        long = "x" * (MAX_MESSAGE_LENGTH + 500)
        props = _exception_event({"$exception_list": [{"type": "E", "value": long}]})["properties"]
        att = build_attestation(props, captured_at=CAPTURED_AT)
        assert att["message"] == "x" * MAX_MESSAGE_LENGTH

    @pytest.mark.parametrize(
        "props,expected_type,expected_message,expected_frame",
        [
            ({"$exception_list": []}, None, None, None),
            ({"$exception_list": [{"type": "KeyError"}]}, "KeyError", None, None),
            ({"$exception_list": [{"value": "boom"}]}, None, "boom", None),
            ({}, None, None, None),
        ],
    )
    def test_tolerates_missing_fields(self, props, expected_type, expected_message, expected_frame):
        att = build_attestation(props, captured_at=CAPTURED_AT)
        assert att["exception_type"] == expected_type
        assert att["message"] == expected_message
        assert att["top_frame"] == expected_frame
        # Absent job context serializes as null, not missing.
        assert att["team_id"] is None and att["run_id"] is None


class TestSign:
    def test_serialization_is_deterministic_and_sorted(self):
        att = build_attestation(_exception_event()["properties"], captured_at=CAPTURED_AT)
        s = serialize_attestation(att)
        assert s == serialize_attestation(att)
        # sort_keys → "captured_at" precedes "exception_type"
        assert s.index('"captured_at"') < s.index('"exception_type"')
        assert " " not in s  # compact separators

    def test_signature_reproduces_with_same_secret(self):
        payload = serialize_attestation(build_attestation(_exception_event()["properties"], captured_at=CAPTURED_AT))
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        assert sign(SECRET, payload) == expected

    def test_different_secret_or_payload_changes_signature(self):
        payload = serialize_attestation(build_attestation(_exception_event()["properties"], captured_at=CAPTURED_AT))
        assert sign(SECRET, payload) != sign("other-secret", payload)
        assert sign(SECRET, payload) != sign(SECRET, payload + "x")


class TestBeforeSendHook:
    def test_signs_exception_event(self):
        hook = make_exception_signer(SECRET)
        event = hook(_exception_event())

        attestation = event["properties"][ATTESTATION_PROPERTY]
        signature = event["properties"][SIGNATURE_PROPERTY]
        # The signature verifies against the exact embedded string.
        assert sign(SECRET, attestation) == signature
        # And the embedded attestation parses to the trusted content.
        parsed = json.loads(attestation)
        assert parsed["message"].startswith("401 Client Error")
        assert parsed["team_id"] == 12345

    def test_passes_through_non_exception_events_untouched(self):
        hook = make_exception_signer(SECRET)
        event = {"event": "schema non-retryable error", "properties": {"sourceType": "Stripe"}}
        assert hook(event) == event
        assert ATTESTATION_PROPERTY not in event["properties"]

    def test_uses_event_timestamp_as_captured_at(self):
        hook = make_exception_signer(SECRET)
        event = hook(_exception_event())
        assert json.loads(event["properties"][ATTESTATION_PROPERTY])["captured_at"] == CAPTURED_AT

    @pytest.mark.parametrize(
        "event",
        [
            {"event": "$exception"},  # no properties
            {"event": "$exception", "properties": None},
            {"event": "$exception", "properties": {}},
            {"properties": {}},  # no event name
            {},
        ],
    )
    def test_never_raises_on_malformed_events(self, event):
        hook = make_exception_signer(SECRET)
        # Should return the event (possibly signed, possibly untouched) without raising.
        assert hook(event) is event

    def test_tampering_with_message_breaks_verification(self):
        hook = make_exception_signer(SECRET)
        event = hook(_exception_event())
        signature = event["properties"][SIGNATURE_PROPERTY]
        # An attacker swaps the displayed message but keeps the (now stale) signature.
        tampered = event["properties"][ATTESTATION_PROPERTY].replace("401 Client Error", "RUN rm -rf /")
        assert sign(SECRET, tampered) != signature
