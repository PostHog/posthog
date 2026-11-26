import re
import json
from datetime import timedelta
from typing import Any, cast

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.http import HttpResponse
from django.test import (
    Client as DjangoClient,
    SimpleTestCase,
    override_settings,
)
from django.urls import reverse
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from parameterized import parameterized

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.session.dbsc import challenges, protocol
from posthog.session.dbsc.binding import OFFER_SESSION_KEY, Binding
from posthog.session.dbsc.cookies import CookieCheck, check_bound_cookie, cookie_name, set_bound_cookie
from posthog.session.models import Session

PrivateKey = ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey


def _ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _rsa_key(bits: int = 2048) -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def _public_jwk(key: PrivateKey) -> dict[str, Any]:
    if isinstance(key, rsa.RSAPrivateKey):
        return json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return json.loads(ECAlgorithm.to_jwk(key.public_key()))


def _proof(
    key: PrivateKey,
    challenge: str,
    *,
    alg: str = "ES256",
    jwk: dict[str, Any] | None = None,
    typ: str = "dbsc+jwt",
) -> str:
    headers: dict[str, Any] = {"typ": typ}
    if jwk is not None:
        headers["jwk"] = jwk
    return jwt.encode({"jti": challenge}, key, algorithm=alg, headers=headers)


class TestDbscProof(SimpleTestCase):
    @parameterized.expand([("es256", _ec_key, "ES256"), ("rs256", _rsa_key, "RS256")])
    def test_registration_proof_signed_by_its_own_key_passes(self, _name, make_key, alg):
        key = make_key()
        proof = protocol.verify_registration_proof(_proof(key, "challenge-1", alg=alg, jwk=_public_jwk(key)))

        assert proof.jti == "challenge-1"
        assert proof.jwk == _public_jwk(key)

    @parameterized.expand(
        [
            ("wrong_type", lambda key: _proof(key, "c", typ="JWT", jwk=_public_jwk(key)), "wrong_type"),
            (
                "unsigned",
                lambda key: jwt.encode({"jti": "c"}, "", algorithm="none", headers={"typ": "dbsc+jwt"}),
                "unsupported_algorithm",
            ),
            ("no_key", lambda key: _proof(key, "c"), "missing_key"),
            ("other_key", lambda key: _proof(key, "c", jwk=_public_jwk(_ec_key())), "bad_signature"),
            (
                "private_key_sent",
                lambda key: _proof(key, "c", jwk={**_public_jwk(key), "d": "secret"}),
                "private_key",
            ),
            (
                "weak_rsa",
                lambda key: (lambda weak: _proof(weak, "c", alg="RS256", jwk=_public_jwk(weak)))(_rsa_key(1024)),
                "weak_key",
            ),
            ("garbage", lambda key: "not-a-jwt", "malformed"),
        ]
    )
    def test_registration_proof_that_does_not_prove_a_device_key_fails(self, _name, make_token, reason):
        with self.assertRaisesMessage(protocol.ProofError, reason):
            protocol.verify_registration_proof(make_token(_ec_key()))

    def test_refresh_proof_must_be_signed_by_the_bound_key(self):
        bound_key, other_key = _ec_key(), _ec_key()
        binding = Binding(id="b1", alg="ES256", jwk=_public_jwk(bound_key), bound_at=timezone.now())

        assert protocol.verify_refresh_proof(_proof(bound_key, "c"), binding).jti == "c"
        with self.assertRaisesMessage(protocol.ProofError, "bad_signature"):
            protocol.verify_refresh_proof(_proof(other_key, "c"), binding)

    @parameterized.expand(
        [
            ("quoted", '"abc.def"', "abc.def"),
            ("quoted_with_params", '"abc";id="xyz"', "abc"),
            ("escaped_quote", '"a\\"b"', 'a"b'),
            ("bare", "abc.def", "abc.def"),
            ("unterminated", '"abc', None),
            ("empty", "", None),
        ]
    )
    def test_parse_sf_string(self, _name, header, expected):
        assert protocol.parse_sf_string(header) == expected


@override_settings(DBSC_COOKIE_SIGNING_KEYS=["new-key", "old-key"], SESSION_COOKIE_SECURE=False)
class TestBoundCookie(SimpleTestCase):
    def _signed(self, binding_id: str) -> str:
        response = HttpResponse()
        set_bound_cookie(response, binding_id)
        return response.cookies[cookie_name()].value

    def test_cookie_checks(self):
        value = self._signed("b1")

        assert check_bound_cookie(value, "b1") == CookieCheck.VALID
        assert check_bound_cookie(value, "b2") == CookieCheck.WRONG_SESSION
        assert check_bound_cookie(None, "b1") == CookieCheck.MISSING
        assert check_bound_cookie(value[:-2] + "xx", "b1") == CookieCheck.BAD_SIGNATURE

    def test_cookie_expires_after_its_grace_period(self):
        with time_machine.travel(timezone.now(), tick=False) as traveller:
            value = self._signed("b1")
            traveller.shift(timedelta(minutes=10, seconds=30))
            assert check_bound_cookie(value, "b1") == CookieCheck.VALID
            traveller.shift(timedelta(minutes=1))
            assert check_bound_cookie(value, "b1") == CookieCheck.EXPIRED

    def test_cookie_signed_with_a_rotated_out_key_still_verifies(self):
        with override_settings(DBSC_COOKIE_SIGNING_KEYS=["old-key"]):
            value = self._signed("b1")

        assert check_bound_cookie(value, "b1") == CookieCheck.VALID


@override_settings(DBSC_ENABLED=True, SESSION_COOKIE_SECURE=False)
class TestDeviceBoundSessionFlow(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.mode = "shadow"
        flag_patch = patch(
            "posthog.session.dbsc.rollout.posthoganalytics.get_feature_flag", side_effect=lambda *a, **k: self.mode
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)
        self.client = cast(Any, DjangoClient())
        self.client.force_login(self.user)
        self.key = _ec_key()

    def _register(self) -> str:
        offer = self.client.get("/api/users/@me/", headers={"Sec-Fetch-Dest": "document"})
        match = re.search(r'challenge="([^"]+)"', offer.headers[protocol.REGISTRATION_HEADER])
        assert match is not None
        proof = _proof(self.key, match.group(1), jwk=_public_jwk(self.key))
        response = self.client.post("/dbsc/start", headers={protocol.RESPONSE_HEADER: f'"{proof}"'})
        assert response.status_code == 200, response.content
        return response.json()["session_identifier"]

    def _session_row(self) -> Session | None:
        return Session.objects.filter(session_key=self.client.session.session_key).first()

    def test_registration_binds_the_session_and_the_bound_cookie_admits_requests(self):
        binding_id = self._register()

        row = self._session_row()
        assert row is not None and row.dbsc_binding is not None
        assert row.dbsc_binding["id"] == binding_id
        assert row.dbsc_binding["jwk"] == _public_jwk(self.key)
        assert self.client.get("/api/users/@me/").status_code == 200

    def test_a_bound_session_does_not_take_a_second_key(self):
        self._register()
        session = self.client.session
        session[OFFER_SESSION_KEY] = "stale-offer"
        session.save()
        challenge = challenges.issue_challenge(challenges.registration_subject("stale-offer"))
        attacker_key = _ec_key()

        response = self.client.post(
            "/dbsc/start",
            headers={protocol.RESPONSE_HEADER: f'"{_proof(attacker_key, challenge, jwk=_public_jwk(attacker_key))}"'},
        )

        assert response.status_code == 409
        row = self._session_row()
        assert row is not None and row.dbsc_binding is not None
        assert row.dbsc_binding["jwk"] == _public_jwk(self.key)

    @parameterized.expand([("shadow", 200, True, False), ("enforce", 302, False, True)])
    def test_session_cookie_without_the_bound_cookie(self, mode, status, session_survives, audited):
        self._register()
        self.mode = mode
        session_key = self.client.session.session_key
        del self.client.cookies[cookie_name()]

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get("/api/users/@me/")

        assert response.status_code == status
        if status == 302:
            assert response.headers["Location"] == "/login?reason=session_unbound"
        assert Session.objects.filter(session_key=session_key).exists() == session_survives
        assert ActivityLog.objects.filter(activity="session_refused_unbound", user=self.user).exists() == audited

    def test_refresh_needs_a_fresh_signed_challenge(self):
        binding_id = self._register()
        session_header = {protocol.SESSION_ID_HEADER: f'"{binding_id}"'}

        challenged = self.client.post("/dbsc/refresh", headers=session_header)
        assert challenged.status_code == 403
        match = re.fullmatch(r'"([^"]+)";id="([^"]+)"', challenged.headers[protocol.CHALLENGE_HEADER])
        assert match is not None and match.group(2) == binding_id

        signed = {**session_header, protocol.RESPONSE_HEADER: f'"{_proof(self.key, match.group(1))}"'}
        refreshed = self.client.post("/dbsc/refresh", headers=signed)
        assert refreshed.status_code == 200
        assert check_bound_cookie(refreshed.cookies[cookie_name()].value, binding_id) == CookieCheck.VALID

        assert self.client.post("/dbsc/refresh", headers=signed).status_code == 403

    def test_refresh_signed_by_another_key_ends_the_session_in_enforce_mode(self):
        binding_id = self._register()
        self.mode = "enforce"
        session_key = self.client.session.session_key
        session_header = {protocol.SESSION_ID_HEADER: f'"{binding_id}"'}
        challenge_header = self.client.post("/dbsc/refresh", headers=session_header).headers[protocol.CHALLENGE_HEADER]
        challenge = protocol.parse_sf_string(challenge_header)
        assert challenge is not None

        response = self.client.post(
            "/dbsc/refresh",
            headers={**session_header, protocol.RESPONSE_HEADER: f'"{_proof(_ec_key(), challenge)}"'},
        )

        assert response.status_code == 401
        assert not Session.objects.filter(session_key=session_key).exists()

    def test_impersonation_keeps_the_staff_members_binding(self):
        self.user.is_staff = True
        self.user.save()
        other_user = User.objects.create_and_join(self.organization, email="other@posthog.com", password="123456")
        binding_id = self._register()
        self.mode = "enforce"

        self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": other_user.id}),
            data={"read_only": "false", "reason": "Test impersonation"},
        )
        impersonated = self._session_row()
        assert impersonated is not None and impersonated.dbsc_binding is not None
        assert impersonated.dbsc_binding["id"] == binding_id
        assert self.client.get("/api/users/@me/").json()["email"] == "other@posthog.com"

        self.client.post("/logout/")
        restored = self._session_row()
        assert restored is not None and restored.dbsc_binding is not None
        assert restored.dbsc_binding["id"] == binding_id
        assert self.client.get("/api/users/@me/").json()["email"] == self.user.email
