import json
import time
import uuid
import importlib
from datetime import timedelta
from io import StringIO
from ipaddress import ip_address
from typing import TypedDict

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import jwt
import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from parameterized import parameterized
from pydantic import JsonValue

from posthog.models import Organization, OrganizationMembership
from posthog.models.ssf import SSFConfiguration, SSFConnection, SSFEvent, SSFStream
from posthog.ssf.serializers import SSFConfigurationSerializer, SSFConnectionSerializer, SSFStreamUpdateSerializer
from posthog.ssf.service import SETValidationError, SSFService
from posthog.ssf.validation import (
    CONTROL_EVENTS,
    POLL_DELIVERY,
    PUSH_DELIVERY,
    STREAM_UPDATED_EVENT,
    VERIFICATION_EVENT,
    SSFOutgoingEventType,
    subjects_match,
    validate_jwks,
)
from posthog.tasks.ssf import cleanup_ssf_events


class BearerHeader(TypedDict):
    HTTP_AUTHORIZATION: str


class TestSSFValidation(SimpleTestCase):
    @parameterized.expand(
        [
            (
                {"format": "email", "email": "member@example.com"},
                {"format": "email", "email": "member@example.com"},
                True,
            ),
            (
                {"format": "email", "email": "member@example.com"},
                {"format": "email", "email": "other@example.com"},
                False,
            ),
            (
                {"format": "complex", "user": {"format": "opaque", "id": "one"}},
                {"format": "complex", "tenant": {"format": "opaque", "id": "two"}},
                True,
            ),
            (
                {"format": "complex", "user": {"format": "opaque", "id": "one"}},
                {"format": "complex", "user": {"format": "opaque", "id": "two"}},
                False,
            ),
        ]
    )
    def test_subject_matching(self, first: dict, second: dict, matches: bool) -> None:
        assert subjects_match(first, second) is matches

    @parameterized.expand(
        [
            ({"issuer": "http://issuer.example.com"}, "issuer"),
            ({"issuer": "https://issuer.example.com?query=one"}, "issuer"),
            ({"transmitter_url": "http://issuer.example.com/metadata"}, "transmitter_url"),
            ({"transmitter_url": "https://issuer.example.com/metadata?query=one"}, "transmitter_url"),
            ({"remote_token": "Bearer not-the-token-only"}, "remote_token"),
            ({"remote_token": "token\nInjected: value"}, "remote_token"),
        ]
    )
    def test_connection_rejects_untrusted_inputs(self, payload: dict, field: str) -> None:
        serializer = SSFConnectionSerializer(
            data={
                "name": "Example",
                "direction": "incoming",
                "issuer": "https://issuer.example.com",
                "remote_token": "example-token",
                **payload,
            }
        )
        assert not serializer.is_valid()
        assert field in serializer.errors

    @parameterized.expand(
        [
            ({"keys": [{"kty": "oct", "k": "not-a-public-key"}]},),
            ({"keys": [{"kty": "RSA", "d": "private-material"}]},),
        ]
    )
    def test_private_key_material_is_not_accepted(self, document: dict) -> None:
        with self.assertRaises(ValueError):
            validate_jwks(document)

    @parameterized.expand(
        [
            ([], True),
            (
                [
                    "https://schemas.openid.net/secevent/caep/event-type/session-revoked",
                    "https://schemas.openid.net/secevent/risc/event-type/account-disabled",
                ],
                True,
            ),
            (["https://example.com/security/custom-event"], False),
            (["$pageview"], False),
        ]
    )
    def test_outgoing_types_are_limited_to_presets(self, values: list[str], valid: bool) -> None:
        for serializer_class, field in (
            (SSFConfigurationSerializer, "event_types"),
            (SSFStreamUpdateSerializer, "events_requested"),
        ):
            serializer = serializer_class(data={field: values}, partial=True)
            assert serializer.is_valid() is valid
            if not valid:
                assert field in serializer.errors


@override_settings(SITE_URL="https://posthog.example.com", SSF_POLL_TIMEOUT_SECONDS=0)
class TestSSF(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.organization.available_product_features = [{"key": "ssf", "name": "SSF"}]
        self.organization.save()
        self.config = SSFConfiguration.objects.create(organization=self.organization, enabled=True)
        SSFService.rotate_signing_key(self.config)
        self.config.save()
        self.outgoing = SSFConnection.objects.create(
            organization=self.organization,
            name="Example receiver",
            direction="outgoing",
            audience="receiver.example.com",
            token_hash=SSFService.token_hash("outgoing-test-credential"),
        )
        self.incoming = SSFConnection.objects.create(
            organization=self.organization,
            name="Example transmitter",
            direction="incoming",
            issuer="https://issuer.example.com",
            legacy_jwks={"keys": [SSFService.public_key(self.config)]},
        )
        self.incoming_stream = SSFStream.objects.create(
            organization=self.organization,
            connection=self.incoming,
            audience="",
            audiences=["posthog.example.com"],
            remote_stream_id="upstream-stream",
            receiver_token_hash=SSFService.token_hash("incoming-test-credential"),
        )
        self.api = f"/api/organizations/{self.organization.id}/ssf/"
        self.protocol = f"/ssf/{self.organization.id}"
        self.authorization: BearerHeader = {"HTTP_AUTHORIZATION": "Bearer outgoing-test-credential"}

    def _stream(self, **payload: object) -> dict:
        response = self.client.post(f"{self.protocol}/stream", payload, format="json", **self.authorization)
        assert response.status_code == 201, response.content
        return response.json()

    def _claims(self, overrides: dict | None = None) -> dict:
        return {
            "iss": self.incoming.issuer,
            "aud": self.incoming_stream.audiences,
            "iat": int(time.time()),
            "jti": uuid.uuid4().hex,
            "sub_id": {"format": "opaque", "id": self.incoming_stream.remote_stream_id},
            "events": {VERIFICATION_EVENT: {}},
            **(overrides or {}),
        }

    def _token(self, *, claims: dict | None = None, headers: dict | None = None) -> str:
        return jwt.encode(
            self._claims(claims),
            self.config.signing_key,
            algorithm="RS256",
            headers={"typ": "secevent+jwt", "kid": self.config.signing_key_id, **(headers or {})},
        )

    def _consume(self, token: str):
        return self.client.post(
            f"{self.protocol}/events/{self.incoming_stream.id}",
            token,
            content_type="application/secevent+jwt",
            HTTP_AUTHORIZATION="Bearer incoming-test-credential",
        )

    def test_discovery_and_key_rotation_preserve_pending_signatures(self) -> None:
        discovery_path = f"/.well-known/ssf-configuration/{self.organization.id}"
        response = self.client.get(discovery_path)
        assert response.status_code == 200
        assert response.json()["issuer"] == SSFService.issuer(self.organization)
        assert self.client.get(self.api).json()["endpoints"]["discovery_url"] == (
            f"https://posthog.example.com{discovery_path}"
        )
        assert response.json()["delivery_methods_supported"] == [POLL_DELIVERY]
        old_key = SSFService.public_key(self.config)
        assert self.client.post(f"{self.api}rotate_key/", {}, format="json").status_code == 200
        keys = self.client.get(f"{self.protocol}/jwks.json").json()["keys"]
        assert old_key in keys and len(keys) == 2 and not any("d" in key for key in keys)
        with time_machine.travel(time.time() + 30 * 86400 + 360, tick=False):
            keys = self.client.get(f"{self.protocol}/jwks.json").json()["keys"]
        assert old_key not in keys and len(keys) == 1

    @parameterized.expand([(1, 403), (8, 200), (15, 200)])
    def test_only_admins_and_owners_can_configure(self, role: int, expected: int) -> None:
        self.organization_membership.level = role
        self.organization_membership.save()
        response = self.client.patch(f"{self.api}configuration/", {"enabled": False}, format="json")
        assert response.status_code == expected, response.content
        self.config.refresh_from_db()
        assert self.config.enabled is (expected != 200)
        assert (
            self.client.patch(
                f"{self.api}connections/{self.outgoing.id}/", {"name": "Renamed"}, format="json"
            ).status_code
            == expected
        )
        read = self.client.get(f"{self.api}connections/")
        assert read.status_code == 200
        assert all("token_hash" not in peer and "remote_token" not in peer for peer in read.json())

    def test_configuration_is_organization_scoped_and_has_no_secrets(self) -> None:
        other = Organization.objects.create(name="Other organization")
        response = self.client.patch(
            f"/api/organizations/{other.id}/ssf/configuration/", {"enabled": True}, format="json"
        )
        assert response.status_code in (403, 404)
        assert not SSFConfiguration.objects.filter(organization=other).exists()
        body = self.client.get(self.api).json()
        options = body["event_type_options"]
        assert len(options) == 4
        selected = [options[0]["key"], options[1]["key"]]
        response = self.client.patch(f"{self.api}configuration/", {"event_types": selected}, format="json")
        assert response.status_code == 200, response.content
        self.config.refresh_from_db()
        assert self.config.event_types == selected
        assert "signing_key" not in body and "receiver_jwks" not in body and "transmitter_token_hash" not in body
        assert (
            self.client.patch(
                f"{self.api}configuration/",
                {"event_types": ["https://example.com/security/custom-event"]},
                format="json",
            ).status_code
            == 400
        )
        assert self.client.patch(f"{self.api}configuration/", {"receiver_issuer": ""}, format="json").status_code == 400
        before = SSFConnection.objects.filter(organization=self.organization).count()
        response = self.client.post(
            f"{self.api}connections/",
            {
                "name": "Invalid",
                "direction": "incoming",
                "issuer": "http://example.com",
                "remote_token": "example-token",
            },
            format="json",
        )
        assert response.status_code == 400
        assert SSFConnection.objects.filter(organization=self.organization).count() == before

    def test_changing_supported_event_types_updates_existing_outgoing_streams(self) -> None:
        revoked = SSFOutgoingEventType.SESSION_REVOKED.value
        disabled = SSFOutgoingEventType.ACCOUNT_DISABLED.value
        self.config.event_types = [revoked]
        self.config.save()
        stream = SSFService.create_outgoing_stream(self.config, self.outgoing, [revoked, disabled], "Existing stream")
        assert stream.events_delivered == [revoked]
        response = self.client.patch(f"{self.api}configuration/", {"event_types": [disabled]}, format="json")
        assert response.status_code == 200, response.content
        stream.refresh_from_db()
        assert stream.events_requested == [revoked, disabled]
        assert stream.events_delivered == [disabled]

    def test_credentials_are_returned_only_once_and_roles_are_separate(self) -> None:
        response = self.client.post(f"{self.api}connections/{self.outgoing.id}/rotate_token/", {}, format="json")
        assert response.status_code == 200, response.content
        token = response.json()["token"]
        assert token.startswith("phssf_")
        self.outgoing.refresh_from_db()
        assert self.outgoing.token_hash != token
        assert self.client.get(f"{self.protocol}/stream", **self.authorization).status_code == 401
        response = self.client.get(f"{self.protocol}/stream", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert response.status_code == 200
        response = self.client.post(
            f"{self.protocol}/events/{self.incoming_stream.id}",
            self._token(),
            content_type="application/secevent+jwt",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 401
        assert token not in self.client.get(f"{self.api}connections/").content.decode()

    @parameterized.expand(
        [
            ("configuration/", "patch"),
            ("rotate_key/", "post"),
            ("connections/{connection}/rotate_token/", "post"),
            ("connections/", "post"),
            ("streams/", "post"),
        ]
    )
    def test_sensitive_writes_require_recent_authentication(self, path: str, method: str) -> None:
        with time_machine.travel(time.time() + settings.SESSION_SENSITIVE_ACTIONS_AGE + 10, tick=False):
            response = getattr(self.client, method)(
                f"{self.api}{path.format(connection=self.outgoing.id)}", {}, format="json"
            )
        assert response.status_code == 403, response.content
        assert response.json()["code"] == "sensitive_action_required_reauth"

    @parameterized.expand([("entitlement",), ("disabled",), ("deactivated",), ("connection_disabled",)])
    def test_entitlement_and_enablement_gate_protocol(self, mode: str) -> None:
        if mode == "entitlement":
            self.organization.available_product_features = []
            self.organization.save()
            assert self.client.get(self.api).status_code == 402
        elif mode == "disabled":
            self.config.enabled = False
            self.config.save()
        elif mode == "deactivated":
            self.organization.is_active = False
            self.organization.save()
            self.client.logout()
        else:
            self.incoming.enabled = False
            self.incoming.save()
            self.outgoing.enabled = False
            self.outgoing.save()
        self.config.refresh_from_db()
        self.incoming_stream.refresh_from_db()
        with self.assertRaises(SETValidationError):
            SSFService.consume_event(self.config, self.incoming_stream, self._token())
        if mode != "connection_disabled":
            assert self.client.get(f"/.well-known/ssf-configuration/{self.organization.id}").status_code == 404
        assert self.client.get(f"{self.protocol}/stream", **self.authorization).status_code in (401, 404)
        assert self._consume(self._token()).status_code in (401, 404)
        assert (
            SSFService.produce_event(self.organization, VERIFICATION_EVENT, {"format": "opaque", "id": "subject"}, {})
            == 0
        )

    def test_stream_management_negotiation_and_immutability(self) -> None:
        stream = self._stream(events_requested=[VERIFICATION_EVENT, "urn:example:unsupported"], description="Original")
        assert stream["events_delivered"] == [VERIFICATION_EVENT]
        assert stream["delivery"]["method"] == POLL_DELIVERY
        assert self.client.get(f"{self.protocol}/stream", **self.authorization).json() == [stream]
        response = self.client.patch(
            f"{self.protocol}/stream",
            {"stream_id": stream["stream_id"], "description": "Updated"},
            format="json",
            **self.authorization,
        )
        assert response.status_code == 200
        assert response.json()["events_requested"] == stream["events_requested"]
        response = self.client.put(
            f"{self.protocol}/stream",
            {"stream_id": stream["stream_id"], "description": "Replaced"},
            format="json",
            **self.authorization,
        )
        assert response.status_code == 200 and response.json()["events_requested"] == []
        response = self.client.patch(
            f"{self.protocol}/stream",
            {"stream_id": stream["stream_id"], "aud": "other.example.com"},
            format="json",
            **self.authorization,
        )
        assert response.status_code == 400
        assert (
            self.client.delete(
                f"{self.protocol}/stream?stream_id={stream['stream_id']}", **self.authorization
            ).status_code
            == 204
        )
        assert self.client.get(f"{self.protocol}/stream", **self.authorization).json() == []

    @parameterized.expand(
        [
            ("get", "stream"),
            ("delete", "stream"),
            ("patch", "stream"),
            ("put", "stream"),
            ("get", "status"),
            ("post", "status"),
            ("post", "subjects:add"),
            ("post", "subjects:remove"),
            ("post", "verify"),
            ("post", "poll"),
        ]
    )
    def test_receiver_cannot_manage_another_receivers_streams(self, method: str, endpoint: str) -> None:
        own = self._stream()
        peer = SSFConnection.objects.create(
            organization=self.organization,
            name="Other receiver",
            direction="outgoing",
            audience=self.outgoing.audience,
            token_hash=SSFService.token_hash("other-credential"),
        )
        other = SSFService.create_outgoing_stream(self.config, peer, CONTROL_EVENTS, "Other stream")
        assert [
            stream["stream_id"] for stream in self.client.get(f"{self.protocol}/stream", **self.authorization).json()
        ] == [own["stream_id"]]
        url = f"{self.protocol}/{endpoint}"
        if endpoint == "poll":
            url += f"/{other.id}"
        payload = {"stream_id": str(other.id), "status": "enabled", "subject": {"format": "opaque", "id": "example"}}
        if method in ("get", "delete"):
            response = getattr(self.client, method)(f"{url}?stream_id={other.id}", **self.authorization)
        else:
            response = getattr(self.client, method)(url, payload, format="json", **self.authorization)
        assert response.status_code == 404, response.content

    def test_customer_api_scopes_connection_foreign_keys(self) -> None:
        other = Organization.objects.create(name="Other")
        peer = SSFConnection.objects.create(
            organization=other, name="Other receiver", direction="outgoing", audience="other"
        )
        response = self.client.post(f"{self.api}streams/", {"connection": str(peer.id)}, format="json")
        assert response.status_code == 400
        response = self.client.get(f"{self.api}connections/{peer.id}/")
        assert response.status_code == 404
        result = self.client.post(
            f"{self.api}connections/", {"name": "New receiver", "direction": "outgoing"}, format="json"
        )
        assert result.status_code == 201, result.content
        assert result.json()["audience"] == result.json()["id"]
        custom = ["https://example.com/security/custom-event"]
        response = self.client.post(
            f"{self.api}streams/", {"connection": str(self.outgoing.id), "events_requested": custom}, format="json"
        )
        assert response.status_code == 400
        stream = SSFService.create_outgoing_stream(self.config, self.outgoing, CONTROL_EVENTS, "Existing")
        response = self.client.patch(f"{self.api}streams/{stream.id}/", {"events_requested": custom}, format="json")
        assert response.status_code == 400
        stream.refresh_from_db()
        assert stream.events_requested == CONTROL_EVENTS

    @time_machine.travel("2026-10-23T12:00:00Z", tick=False)
    def test_verification_poll_redelivery_and_acknowledgement(self) -> None:
        stream = self._stream()
        assert (
            self.client.post(
                f"{self.protocol}/verify",
                {"stream_id": stream["stream_id"], "state": "verification-nonce"},
                format="json",
                **self.authorization,
            ).status_code
            == 204
        )
        poll_url = f"{self.protocol}/poll/{stream['stream_id']}"
        response = self.client.post(
            poll_url, {"maxEvents": 1, "returnImmediately": True}, format="json", **self.authorization
        )
        assert response.status_code == 200, response.content
        sets = response.json()["sets"]
        jti, token = next(iter(sets.items()))
        claims = jwt.decode(
            token,
            jwt.PyJWK.from_dict(SSFService.public_key(self.config)).key,
            algorithms=["RS256"],
            audience=self.outgoing.audience,
        )
        assert claims["sub_id"] == {"format": "opaque", "id": stream["stream_id"]}
        assert claims["events"][VERIFICATION_EVENT]["state"] == "verification-nonce"
        assert "sub" not in claims and "exp" not in claims and jwt.get_unverified_header(token)["typ"] == "secevent+jwt"
        assert (
            self.client.post(poll_url, {"returnImmediately": True}, format="json", **self.authorization).json()["sets"]
            == sets
        )
        assert (
            self.client.post(
                poll_url, {"maxEvents": 0, "ack": [jti], "returnImmediately": True}, format="json", **self.authorization
            ).json()["sets"]
            == {}
        )
        assert not SSFEvent.objects.filter(organization=self.organization, jti=jti).exists()
        other = self._stream(events_requested=[])
        assert (
            SSFService.produce_event(
                self.organization, VERIFICATION_EVENT, {"format": "opaque", "id": other["stream_id"]}, {}
            )
            == 1
        )
        assert (
            self.client.post(poll_url, {"returnImmediately": True}, format="json", **self.authorization).json()["sets"]
            == {}
        )
        other_poll = f"{self.protocol}/poll/{other['stream_id']}"
        assert (
            len(
                self.client.post(other_poll, {"returnImmediately": True}, format="json", **self.authorization).json()[
                    "sets"
                ]
            )
            == 1
        )
        SSFEvent.objects.filter(organization=self.organization, stream_id=other["stream_id"]).update(
            created_at=timezone.now() - timedelta(days=30, minutes=1)
        )
        assert (
            self.client.post(other_poll, {"returnImmediately": True}, format="json", **self.authorization).json()[
                "sets"
            ]
            == {}
        )

    def test_subject_filtering_pause_disable_and_error_acknowledgements(self) -> None:
        event_type = "https://schemas.openid.net/secevent/risc/event-type/account-disabled"
        legacy_custom_type = "https://example.com/security/legacy-event"
        self.config.event_types = [event_type, legacy_custom_type]
        self.config.save()
        assert legacy_custom_type not in SSFService.supported_event_types(self.config)
        assert SSFConfigurationSerializer(self.config).data["event_types"] == [event_type]
        stream = self._stream(events_requested=[event_type])
        assert legacy_custom_type not in stream["events_supported"]
        subject: dict[str, JsonValue] = {"format": "email", "email": "member@example.com"}
        with self.assertRaises(ValueError):
            SSFService.produce_event(self.organization, legacy_custom_type, subject, {})
        assert SSFService.produce_event(self.organization, event_type, subject, {}) == 0
        assert (
            self.client.post(
                f"{self.protocol}/subjects:add",
                {"stream_id": stream["stream_id"], "subject": subject},
                format="json",
                **self.authorization,
            ).status_code
            == 200
        )
        assert SSFService.produce_event(self.organization, event_type, subject, {}) == 1
        poll_url = f"{self.protocol}/poll/{stream['stream_id']}"
        status_url = f"{self.protocol}/status"
        self.client.post(
            status_url, {"stream_id": stream["stream_id"], "status": "paused"}, format="json", **self.authorization
        )
        assert self.client.post(poll_url, {}, format="json", **self.authorization).json()["sets"] == {}
        assert SSFService.produce_event(self.organization, event_type, subject, {}) == 1
        self.client.post(
            status_url, {"stream_id": stream["stream_id"], "status": "enabled"}, format="json", **self.authorization
        )
        response = self.client.post(poll_url, {"maxEvents": 1}, format="json", **self.authorization)
        assert response.json()["moreAvailable"] is True
        jti = next(iter(response.json()["sets"]))
        response = self.client.post(
            poll_url, {"setErrs": {jti: {"err": "invalid_key"}}}, format="json", **self.authorization
        )
        assert jti not in response.json()["sets"]
        self.client.post(
            status_url, {"stream_id": stream["stream_id"], "status": "disabled"}, format="json", **self.authorization
        )
        assert SSFService.produce_event(self.organization, event_type, subject, {}) == 0
        assert not SSFEvent.objects.filter(organization=self.organization, stream_id=stream["stream_id"]).exists()
        assert (
            self.client.post(
                f"{self.protocol}/subjects:remove",
                {"stream_id": stream["stream_id"], "subject": subject},
                format="json",
                **self.authorization,
            ).status_code
            == 204
        )

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_receiver_is_durable_idempotent_and_analytics_exclude_payloads(self, capture) -> None:
        token = self._token()
        with self.captureOnCommitCallbacks(execute=True):
            assert self._consume(token).status_code == 202
            assert self._consume(token).status_code == 202
        assert SSFEvent.objects.filter(organization=self.organization, direction="incoming").count() == 1
        assert [call.kwargs["event"] for call in capture.call_args_list].count("ssf event consumed") == 1
        self.incoming_stream.refresh_from_db()
        assert self.incoming_stream.last_verified_at is not None
        serialized_calls = str(capture.call_args_list)
        assert (
            token not in serialized_calls
            and "upstream-stream" not in serialized_calls
            and self.config.signing_key not in serialized_calls
        )
        segments = token.split(".")
        segments[-1] = ("A" if segments[-1][0] != "A" else "B") + segments[-1][1:]
        response = self._consume(".".join(segments))
        assert response.status_code == 400 and response.json()["err"] == "invalid_key"

    def test_incoming_credentials_and_audiences_are_stream_scoped(self) -> None:
        second = SSFStream.objects.create(
            organization=self.organization,
            connection=self.incoming,
            audience="",
            audiences=["another-audience"],
            remote_stream_id="another-stream",
            receiver_token_hash=SSFService.token_hash("second-credential"),
        )
        path = f"{self.protocol}/events/{second.id}"
        assert (
            self.client.post(
                path,
                self._token(),
                content_type="application/secevent+jwt",
                HTTP_AUTHORIZATION="Bearer incoming-test-credential",
            ).status_code
            == 401
        )
        response = self.client.post(
            path, self._token(), content_type="application/secevent+jwt", HTTP_AUTHORIZATION="Bearer second-credential"
        )
        assert response.status_code == 400 and response.json()["err"] == "invalid_audience"
        self.incoming.audience = self.incoming_stream.audiences[0]
        self.incoming.save()
        self.incoming_stream.audiences = [*self.incoming_stream.audiences, "unexpected-alias"]
        self.incoming_stream.save()
        response = self._consume(self._token(claims={"aud": "unexpected-alias"}))
        assert response.status_code == 400 and response.json()["err"] == "invalid_audience"
        response = self.client.post(
            f"{self.protocol}/events",
            self._token(),
            content_type="application/secevent+jwt",
            HTTP_AUTHORIZATION="Bearer incoming-test-credential",
        )
        assert response.status_code == 202

    def test_es256_and_single_key_without_kid_are_accepted(self) -> None:
        key = ec.generate_private_key(ec.SECP256R1())
        self.incoming.legacy_jwks = {"keys": [jwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True)]}
        self.incoming.save()
        validate_jwks(self.incoming.legacy_jwks)
        token = jwt.encode(
            self._claims({"iat": time.time() - 1.5}), key, algorithm="ES256", headers={"typ": "secevent+jwt"}
        )
        assert self._consume(token).status_code == 202

    @parameterized.expand(
        [
            ({"iss": "https://other.example.com"}, {}, "invalid_issuer"),
            ({"aud": "other-receiver"}, {}, "invalid_audience"),
            ({"sub": "forbidden"}, {}, "invalid_request"),
            ({"exp": "future"}, {}, "invalid_request"),
            ({"iat": 1}, {}, "invalid_request"),
            ({"iat": float("inf")}, {}, "invalid_request"),
            ({"events": []}, {}, "invalid_request"),
            ({"events": {"not-a-uri": {}}}, {}, "invalid_request"),
            ({"jti": ""}, {}, "invalid_request"),
            ({}, {"typ": "JWT"}, "invalid_request"),
            ({}, {"crit": []}, "invalid_request"),
            ({}, {"kid": "unknown-key"}, "invalid_key"),
            ({"events": {VERIFICATION_EVENT: {"state": "unexpected"}}}, {}, "invalid_state"),
            ({"events": {VERIFICATION_EVENT: {}}}, {}, "invalid_state", "expected-state"),
            (
                {"sub_id": {"format": "complex", "unknown": {"format": "opaque", "id": "subject"}}},
                {},
                "invalid_request",
            ),
            ({"events": {STREAM_UPDATED_EVENT: {"status": "failed"}}}, {}, "invalid_request"),
        ]
    )
    def test_receiver_rejects_invalid_tokens(
        self, claims: dict, headers: dict, code: str, expected_state: str | None = None
    ) -> None:
        if claims.get("exp") == "future":
            claims = {**claims, "exp": int(time.time()) + 3600}
        self.incoming_stream.verification_state = expected_state
        self.incoming_stream.save()
        self.incoming.metadata = {"critical_subject_members": ["unknown"]}
        self.incoming.save()
        response = self._consume(self._token(claims=claims, headers=headers))
        assert response.status_code == 400, response.content
        assert response.json()["err"] == code and response["Content-Language"] == "en"
        assert not SSFEvent.objects.filter(organization=self.organization).exists()

    @parameterized.expand([("malformed", "not-a-jwt"), ("oversized", "x" * 65537), ("empty", "")])
    def test_receiver_rejects_malformed_requests(self, _name: str, token: str) -> None:
        response = self._consume(token)
        assert response.status_code == 400 and response.json()["err"] == "invalid_request"

    @time_machine.travel("2026-10-23T12:00:00Z", tick=False)
    def test_cleanup_keeps_replay_protection_through_clock_skew(self) -> None:
        assert self._consume(self._token()).status_code == 202
        recent = SSFEvent.objects.get(organization=self.organization)
        for age, retained in ((timedelta(days=30, minutes=4), True), (timedelta(days=30, minutes=6), False)):
            SSFEvent.objects.filter(organization=self.organization, pk=recent.pk).update(
                created_at=timezone.now() - age
            )
            cleanup_ssf_events()
            assert SSFEvent.objects.filter(organization=self.organization, pk=recent.pk).exists() is retained

    def test_disconnect_preserves_incoming_replay_receipts(self) -> None:
        token = self._token()
        assert self._consume(token).status_code == 202
        assert self.client.delete(f"{self.api}streams/{self.incoming_stream.id}/").status_code == 204
        receipt = SSFEvent.objects.get(organization=self.organization)
        assert receipt.stream_id is None and receipt.token == token
        assert self._consume(token).status_code == 404

    def test_reencryption_is_explicit_and_preserves_token_contents(self) -> None:
        token = self._token()
        assert self._consume(token).status_code == 202
        event = SSFEvent.objects.get(organization=self.organization)
        with connection.cursor() as cursor:
            cursor.execute("SELECT token FROM posthog_ssfevent WHERE id = %s", [event.id])
            original = cursor.fetchone()[0]
        call_command("reencrypt_ssf_fields", organization_id=self.organization.id, stdout=StringIO())
        with connection.cursor() as cursor:
            cursor.execute("SELECT token FROM posthog_ssfevent WHERE id = %s", [event.id])
            assert cursor.fetchone()[0] == original
        call_command("reencrypt_ssf_fields", organization_id=self.organization.id, apply=True, stdout=StringIO())
        with connection.cursor() as cursor:
            cursor.execute("SELECT token FROM posthog_ssfevent WHERE id = %s", [event.id])
            assert cursor.fetchone()[0] != original
        event.refresh_from_db()
        self.incoming_stream.refresh_from_db()
        assert event.token == token and SSFService.validate_token(self.incoming_stream, token)["jti"] == event.jti

    def test_migration_preserves_existing_singleton_configuration(self) -> None:
        self.config.transmitter_audience = "legacy-receiver"
        self.config.transmitter_token_hash = SSFService.token_hash("legacy-outgoing")
        self.config.receiver_issuer = "https://legacy.example.com"
        self.config.receiver_audience = "legacy-audience"
        self.config.receiver_stream_id = "legacy-stream"
        self.config.receiver_jwks = {"keys": [SSFService.public_key(self.config)]}
        self.config.receiver_token_hash = SSFService.token_hash("legacy-incoming")
        self.config.receiver_verification_state = "legacy-state"
        self.config.save()
        old = SSFStream.objects.create(
            organization=self.organization, audience="legacy-receiver", events_requested=[VERIFICATION_EVENT]
        )
        migration = importlib.import_module("posthog.migrations.1412_ssf_connections")
        migration.backfill_connections(apps, connection.schema_editor())
        old.refresh_from_db()
        assert old.connection is not None
        assert old.connection.token_hash == self.config.transmitter_token_hash
        assert old.audiences == ["legacy-receiver"]
        incoming = SSFStream.objects.select_related("connection").get(
            organization=self.organization, remote_stream_id="legacy-stream"
        )
        assert incoming.connection is not None
        assert incoming.receiver_token_hash == self.config.receiver_token_hash
        assert (
            incoming.verification_state == "legacy-state"
            and incoming.connection.legacy_jwks == self.config.receiver_jwks
        )
        assert incoming.connection.issuer == self.config.receiver_issuer


class ExampleTransmitter:
    def __init__(self, issuer: str, jwks: dict) -> None:
        self.issuer = issuer
        self.jwks = jwks
        self.streams: dict[str, dict] = {}
        self.requests: list[tuple[str, str, dict, dict]] = []
        self.metadata_path = "/.well-known/ssf-configuration/tenant"
        self.lose_create_response = False
        self.limit_creates = False

    def request(self, _transport, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.method, path, dict(request.headers), body))
        metadata = {
            "issuer": self.issuer,
            "jwks_uri": "https://keys.example.com/jwks",
            "delivery_methods_supported": [PUSH_DELIVERY],
            "configuration_endpoint": "https://issuer.example.com/streams",
            "status_endpoint": "https://issuer.example.com/status",
            "verification_endpoint": "https://issuer.example.com/verify",
            "add_subject_endpoint": "https://issuer.example.com/subjects:add",
            "remove_subject_endpoint": "https://issuer.example.com/subjects:remove",
        }
        if path == self.metadata_path:
            return httpx.Response(200, json=metadata)
        if path == "/jwks":
            return httpx.Response(200, json=self.jwks)
        if request.headers.get("Authorization") != "Bearer example-api-token":
            return httpx.Response(401)
        if path == "/streams":
            if request.method == "GET":
                return httpx.Response(200, json=list(self.streams.values()))
            if request.method == "DELETE":
                self.streams.pop(request.url.params["stream_id"], None)
                return httpx.Response(204)
            if self.limit_creates and request.method == "POST":
                return httpx.Response(429, headers={"Retry-After": "120"})
            remote_id = body.get("stream_id", f"remote-{len(self.streams) + 1}")
            result = {
                "iss": self.issuer,
                "aud": f"audience-{remote_id}",
                "stream_id": remote_id,
                "events_delivered": body["events_requested"],
                **body,
            }
            self.streams[remote_id] = result
            if self.lose_create_response and request.method == "POST":
                self.lose_create_response = False
                raise httpx.ReadTimeout("Synthetic lost create response", request=request)
            return httpx.Response(201 if request.method == "POST" else 200, json=result)
        if path == "/status":
            if request.method == "POST":
                self.streams[body["stream_id"]]["status"] = body["status"]
                remote_id = body["stream_id"]
            else:
                remote_id = request.url.params["stream_id"]
            return httpx.Response(
                200, json={"stream_id": remote_id, "status": self.streams[remote_id].get("status", "enabled")}
            )
        if path in ("/verify", "/subjects:add", "/subjects:remove"):
            return httpx.Response(204 if path != "/subjects:add" else 200)
        return httpx.Response(404)


@override_settings(SITE_URL="https://posthog.example.com", FORCE_URL_VALIDATION=True, SSRF_TRUSTED_PROXY_URLS=[])
class TestSSFRemoteProvisioning(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.organization.available_product_features = [{"key": "ssf", "name": "SSF"}]
        self.organization.save()
        self.config = SSFConfiguration.objects.create(organization=self.organization, enabled=True)
        SSFService.rotate_signing_key(self.config)
        self.config.save()
        self.provider = ExampleTransmitter(
            "https://issuer.example.com/tenant", {"keys": [SSFService.public_key(self.config)]}
        )
        self.dns = patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")})
        self.http = patch(
            "posthog.ssf.remote.pinned_client",
            side_effect=lambda url, pinned_ips, **kwargs: httpx.Client(
                transport=httpx.MockTransport(lambda request: self.provider.request(None, request)),
                follow_redirects=False,
            ),
        )
        self.proxy = patch.dict("os.environ", {"HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": ""})
        self.dns.start()
        self.client_factory = self.http.start()
        self.proxy.start()
        self.addCleanup(self.dns.stop)
        self.addCleanup(self.http.stop)
        self.addCleanup(self.proxy.stop)
        self.api = f"/api/organizations/{self.organization.id}/ssf/"

    def _connection(self) -> dict:
        response = self.client.post(
            f"{self.api}connections/",
            {
                "name": "Example transmitter",
                "direction": "incoming",
                "issuer": self.provider.issuer,
                "remote_token": "example-api-token",
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        assert "remote_token" not in response.json()
        return response.json()

    def _stream(self, peer: dict) -> dict:
        response = self.client.post(
            f"{self.api}streams/", {"connection": peer["id"], "events_requested": [VERIFICATION_EVENT]}, format="json"
        )
        assert response.status_code == 201, response.content
        return response.json()

    def test_api_discovers_keys_provisions_multiple_streams_and_verifies_delivery(self) -> None:
        peer = self._connection()
        assert peer["jwks_uri"] == "https://keys.example.com/jwks"
        first, second = self._stream(peer), self._stream(peer)
        assert first["status"] == second["status"] == "enabled"
        assert first["id"] != second["id"] and first["remote_stream_id"] != second["remote_stream_id"]
        assert len(self.provider.streams) == 2
        keys_calls = [call for call in self.provider.requests if call[1] == "/jwks"]
        assert keys_calls and all("authorization" not in headers for _, _, headers, _ in keys_calls)
        assert all(
            call.args[1] == {ip_address("93.184.216.34")} and call.kwargs["follow_redirects"] is False
            for call in self.client_factory.call_args_list
        )
        stream = SSFStream.objects.select_related("connection").get(organization=self.organization, pk=first["id"])
        upstream = self.provider.streams[stream.remote_stream_id]
        nonce = stream.verification_state
        assert nonce and first["verification_pending"] is True
        claims = {
            "iss": self.provider.issuer,
            "aud": stream.audiences,
            "jti": uuid.uuid4().hex,
            "iat": int(time.time()),
            "sub_id": {"format": "opaque", "id": stream.remote_stream_id},
            "events": {VERIFICATION_EVENT: {"state": nonce}},
        }
        token = jwt.encode(
            claims,
            self.config.signing_key,
            algorithm="RS256",
            headers={"typ": "secevent+jwt", "kid": self.config.signing_key_id},
        )
        response = self.client.post(
            upstream["delivery"]["endpoint_url"].removeprefix(settings.SITE_URL),
            token,
            content_type="application/secevent+jwt",
            HTTP_AUTHORIZATION=upstream["delivery"]["authorization_header"],
        )
        assert response.status_code == 202, response.content
        result = self.client.get(f"{self.api}streams/{stream.id}/").json()
        assert result["last_verified_at"] and result["verification_pending"] is False
        response = self.client.patch(
            f"{self.api}streams/{stream.id}/", {"description": "Updated account events"}, format="json"
        )
        assert response.status_code == 200, response.content
        assert response.json()["description"] == "Updated account events" and len(self.provider.streams) == 2
        assert (
            self.provider.streams[stream.remote_stream_id]["delivery"]["authorization_header"]
            == upstream["delivery"]["authorization_header"]
        )
        serialized = self.client.get(f"{self.api}connections/").content + self.client.get(f"{self.api}streams/").content
        assert (
            b"example-api-token" not in serialized
            and upstream["delivery"]["authorization_header"].encode() not in serialized
        )
        assert (
            self.client.post(f"{self.api}streams/{stream.id}/status/", {"status": "paused"}, format="json").json()[
                "status"
            ]
            == "paused"
        )
        assert (
            self.client.post(
                f"{self.api}streams/{stream.id}/add_subject/",
                {"subject": {"format": "email", "email": "member@example.com"}},
                format="json",
            ).status_code
            == 204
        )
        assert self.client.delete(f"{self.api}streams/{stream.id}/").status_code == 204
        assert stream.remote_stream_id not in self.provider.streams

    def test_rotation_refreshes_jwks_without_manual_key_updates(self) -> None:
        peer = self._connection()
        row = self._stream(peer)
        stream = SSFStream.objects.select_related("connection").get(organization=self.organization, pk=row["id"])
        SSFService.rotate_signing_key(self.config)
        self.config.save()
        self.provider.jwks = {"keys": [SSFService.public_key(self.config)]}
        claims = {
            "iss": self.provider.issuer,
            "aud": stream.audiences,
            "jti": uuid.uuid4().hex,
            "iat": int(time.time()),
            "sub_id": {"format": "opaque", "id": stream.remote_stream_id},
            "events": {VERIFICATION_EVENT: {"state": stream.verification_state}},
        }
        token = jwt.encode(
            claims,
            self.config.signing_key,
            algorithm="RS256",
            headers={"typ": "secevent+jwt", "kid": self.config.signing_key_id},
        )
        before = len([call for call in self.provider.requests if call[1] == "/jwks"])
        response = self.client.post(
            stream.endpoint_url.removeprefix(settings.SITE_URL),
            token,
            content_type="application/secevent+jwt",
            HTTP_AUTHORIZATION=f"Bearer {stream.receiver_token}",
        )
        assert response.status_code == 202, response.content
        assert len([call for call in self.provider.requests if call[1] == "/jwks"]) == before + 1
        bad = jwt.encode(
            claims, self.config.signing_key, algorithm="RS256", headers={"typ": "secevent+jwt", "kid": "unknown-again"}
        )
        assert (
            self.client.post(
                stream.endpoint_url.removeprefix(settings.SITE_URL),
                bad,
                content_type="application/secevent+jwt",
                HTTP_AUTHORIZATION=f"Bearer {stream.receiver_token}",
            ).status_code
            == 400
        )
        assert len([call for call in self.provider.requests if call[1] == "/jwks"]) == before + 1

    def test_lost_create_response_recovers_without_duplicate_upstream_stream(self) -> None:
        peer = self._connection()
        self.provider.lose_create_response = True
        failed = self._stream(peer)
        assert failed["status"] == "failed" and len(self.provider.streams) == 1
        response = self.client.post(f"{self.api}streams/{failed['id']}/provision/", {}, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["status"] == "enabled" and len(self.provider.streams) == 1

    def test_upstream_rate_limit_is_honored_on_retry(self) -> None:
        peer = self._connection()
        self.provider.limit_creates = True
        failed = self._stream(peer)
        assert failed["status"] == "failed" and failed["retry_at"]
        count = len(self.provider.requests)
        response = self.client.post(f"{self.api}streams/{failed['id']}/provision/", {}, format="json")
        assert response.status_code == 429 and int(response["Retry-After"]) > 0
        assert len(self.provider.requests) == count

    @parameterized.expand(
        [("http://issuer.example.com",), ("https://127.0.0.1",), ("https://user:password@issuer.example.com",)]
    )
    def test_discovery_rejects_unsafe_urls_without_outbound_requests(self, issuer: str) -> None:
        response = self.client.post(
            f"{self.api}connections/",
            {"name": "Unsafe", "direction": "incoming", "issuer": issuer, "remote_token": "example-api-token"},
            format="json",
        )
        assert response.status_code == 400, response.content
        assert self.provider.requests == []

    def test_manual_transmitter_url_overrides_issuer_discovery_path(self) -> None:
        self.provider.metadata_path = "/custom/ssf-metadata"
        response = self.client.post(
            f"{self.api}connections/",
            {
                "name": "Custom metadata",
                "direction": "incoming",
                "issuer": self.provider.issuer,
                "transmitter_url": "https://issuer.example.com/custom/ssf-metadata",
                "remote_token": "example-api-token",
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        assert response.json()["transmitter_url"] == "https://issuer.example.com/custom/ssf-metadata"
        assert response.json()["jwks_uri"] == "https://keys.example.com/jwks"
        assert any(call[1] == "/custom/ssf-metadata" for call in self.provider.requests)
        assert not any(call[1] == "/.well-known/ssf-configuration/tenant" for call in self.provider.requests)
        cleared = self.client.patch(
            f"{self.api}connections/{response.json()['id']}/", {"transmitter_url": ""}, format="json"
        )
        assert cleared.status_code == 200, cleared.content
        assert cleared.json()["transmitter_url"] == ""

    def test_discovery_rejects_issuer_mismatch(self) -> None:
        response = self.client.post(
            f"{self.api}connections/",
            {
                "name": "Wrong issuer",
                "direction": "incoming",
                "issuer": "https://issuer.example.com/tenant/",
                "remote_token": "example-api-token",
            },
            format="json",
        )
        assert response.status_code == 400
        assert not SSFConnection.objects.filter(organization=self.organization).exists()
