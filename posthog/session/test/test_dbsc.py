import re
import json
import time
import dataclasses
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
from posthog.session.dbsc.decisions import Action, BoundRequest, decide
from posthog.session.dbsc.rollout import Mode
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
    @parameterized.expand(
        [
            ("es256", _ec_key, "ES256", ("kty", "crv", "x", "y")),
            ("rs256", _rsa_key, "RS256", ("kty", "n", "e")),
        ]
    )
    def test_registration_proof_signed_by_its_own_key_passes(self, _name, make_key, alg, key_members):
        key = make_key()
        jwk = {**_public_jwk(key), "kid": "device-1"}
        proof = protocol.verify_registration_proof(_proof(key, "challenge-1", alg=alg, jwk=jwk))

        assert proof.jti == "challenge-1"
        assert proof.jwk == {member: jwk[member] for member in key_members}

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
            ("non_string_coordinate", lambda key: _proof(key, "c", jwk={**_public_jwk(key), "x": 1}), "malformed_key"),
            (
                "nul_in_coordinate",
                lambda key: _proof(key, "c", jwk={**_public_jwk(key), "x": _public_jwk(key)["x"] + "\u0000" * 4}),
                "malformed_key",
            ),
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


_BASE_FACTS = BoundRequest(
    check=CookieCheck.MISSING,
    mode=Mode.ENFORCE,
    binding_age=timedelta(minutes=5),
    cross_site=False,
    navigation=False,
    bounced=False,
    refresh_skipped=False,
)


class TestRefusalDecision(SimpleTestCase):
    @parameterized.expand(
        [
            ("valid_cookie", {"check": CookieCheck.VALID}, Action.ALLOW),
            ("flag_off", {"mode": Mode.OFF}, Action.ALLOW),
            ("fresh_binding_missing", {"binding_age": timedelta(seconds=5)}, Action.ALLOW),
            (
                "fresh_binding_old_cookie",
                {"binding_age": timedelta(seconds=5), "check": CookieCheck.WRONG_SESSION},
                Action.ALLOW,
            ),
            (
                "fresh_binding_expired",
                {"binding_age": timedelta(seconds=5), "check": CookieCheck.EXPIRED},
                Action.END_SESSION,
            ),
            ("shadow", {"mode": Mode.SHADOW}, Action.RECORD),
            ("same_origin", {}, Action.END_SESSION),
            ("cross_site_navigation", {"cross_site": True, "navigation": True}, Action.BOUNCE),
            (
                "cross_site_navigation_after_bounce",
                {"cross_site": True, "navigation": True, "bounced": True},
                Action.END_SESSION,
            ),
            ("cross_site_fetch", {"cross_site": True}, Action.REJECT),
            ("refresh_skipped", {"refresh_skipped": True}, Action.RETRY_LATER),
        ]
    )
    def test_decide(self, _name, overrides, expected):
        assert decide(dataclasses.replace(_BASE_FACTS, **overrides)) == expected


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

    def _register(self, extra_jwk_members: dict[str, str] | None = None) -> str:
        offer = self.client.get("/api/users/@me/", headers={"Sec-Fetch-Dest": "document"})
        match = re.search(r'challenge="([^"]+)"', offer.headers[protocol.REGISTRATION_HEADER])
        assert match is not None
        proof = _proof(self.key, match.group(1), jwk={**_public_jwk(self.key), **(extra_jwk_members or {})})
        response = self.client.post("/dbsc/start", headers={protocol.RESPONSE_HEADER: f'"{proof}"'})
        assert response.status_code == 200, response.content
        return response.json()["session_identifier"]

    def _session_row(self) -> Session | None:
        return Session.objects.filter(session_key=self.client.session.session_key).first()

    def _past_grace(self) -> time_machine.travel:
        return time_machine.travel(timezone.now() + timedelta(minutes=2), tick=False)

    def test_registration_binds_the_session_and_stores_only_the_key(self):
        binding_id = self._register(extra_jwk_members={"kid": "\u0000"})

        row = self._session_row()
        assert row is not None and row.dbsc_binding is not None
        assert row.dbsc_binding["id"] == binding_id
        assert row.dbsc_binding["jwk"] == _public_jwk(self.key)
        assert self.client.get("/api/users/@me/").status_code == 200

    def test_password_login_response_carries_the_registration_offer(self):
        self.client.logout()

        response = self.client.post(
            "/api/login",
            {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert protocol.REGISTRATION_HEADER in response.headers

    def test_registration_offer_expires(self):
        with time_machine.travel(timezone.now() + timedelta(minutes=11), tick=False):
            page = self.client.get("/api/users/@me/", headers={"Sec-Fetch-Dest": "document"})

        assert protocol.REGISTRATION_HEADER not in page.headers

    def test_a_bound_session_does_not_take_a_second_key(self):
        self._register()
        session = self.client.session
        session[OFFER_SESSION_KEY] = {"id": "stale-offer", "expires_at": time.time() + 600}
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

    @parameterized.expand(
        [
            ("shadow", "shadow", "/api/users/@me/", timedelta(minutes=2), 200, True),
            ("enforce_fresh_binding", "enforce", "/api/users/@me/", timedelta(0), 200, True),
            ("enforce_api", "enforce", "/api/users/@me/", timedelta(minutes=2), 401, False),
            ("enforce_page", "enforce", "/insights", timedelta(minutes=2), 302, False),
            ("enforce_unrouted_dbsc_path", "enforce", "/dbsc/anything", timedelta(minutes=2), 302, False),
        ]
    )
    def test_session_cookie_without_the_bound_cookie(self, _name, mode, path, elapsed, status, session_survives):
        self._register()
        self.mode = mode
        session_key = self.client.session.session_key
        del self.client.cookies[cookie_name()]

        with (
            time_machine.travel(timezone.now() + elapsed, tick=False),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.get(path)

        assert response.status_code == status
        if status == 302:
            assert response.headers["Location"] == "/login?reason=session_unbound"
        if status == 401:
            assert response.json()["code"] == "session_unbound"
        assert Session.objects.filter(session_key=session_key).exists() == session_survives
        ended = not session_survives
        assert ActivityLog.objects.filter(activity="session_refused_unbound", user=self.user).exists() == ended
        assert ActivityLog.objects.filter(activity="logged_out", user=self.user).exists() == ended

    def test_cross_site_navigation_bounces_through_our_origin_before_refusing(self):
        self._register()
        self.mode = "enforce"
        session_key = self.client.session.session_key
        del self.client.cookies[cookie_name()]
        cross_site_navigation = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}

        with self._past_grace():
            bounced = self.client.get("/insights", headers=cross_site_navigation)
            assert bounced.status_code == 200
            assert b'http-equiv="refresh"' in bounced.content
            assert Session.objects.filter(session_key=session_key).exists()

            refused = self.client.get("/insights", headers=cross_site_navigation)

        assert refused.status_code == 302
        assert not Session.objects.filter(session_key=session_key).exists()

    @parameterized.expand(
        [
            ("cross_site_fetch", {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"}),
            ("extension", {"Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "cors"}),
            ("foreign_origin", {"Sec-Fetch-Mode": "cors", "Origin": "chrome-extension://abc"}),
        ]
    )
    def test_request_started_elsewhere_is_rejected_without_ending_the_session(self, _name, headers):
        self._register()
        self.mode = "enforce"
        session_key = self.client.session.session_key
        del self.client.cookies[cookie_name()]

        with self._past_grace():
            response = self.client.get("/api/users/@me/", headers=headers)

        assert response.status_code == 401
        assert Session.objects.filter(session_key=session_key).exists()

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

    def test_refresh_status_codes_for_requests_it_cannot_serve(self):
        self._register()

        assert self.client.post("/dbsc/refresh", headers={protocol.SESSION_ID_HEADER: '"\u00e9"'}).status_code == 401
        with override_settings(DBSC_COOKIE_SIGNING_KEYS=[]):
            assert self.client.post("/dbsc/refresh", headers={protocol.SESSION_ID_HEADER: '"x"'}).status_code == 503

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

    def _impersonate(self) -> tuple[str, User]:
        self.user.is_staff = True
        self.user.save()
        other_user = User.objects.create_and_join(self.organization, email="other@posthog.com", password="123456")
        binding_id = self._register()
        self.client.post(
            reverse("loginas-user-login", kwargs={"user_id": other_user.id}),
            data={"read_only": "false", "reason": "Test impersonation"},
        )
        return binding_id, other_user

    def test_impersonation_keeps_the_staff_members_binding(self):
        self.mode = "enforce"
        binding_id, other_user = self._impersonate()

        impersonated = self._session_row()
        assert impersonated is not None and impersonated.dbsc_binding is not None
        assert impersonated.dbsc_binding["id"] == binding_id
        assert self.client.get("/api/users/@me/").json()["email"] == other_user.email

        self.client.post("/logout/")
        restored = self._session_row()
        assert restored is not None and restored.dbsc_binding is not None
        assert restored.dbsc_binding["id"] == binding_id
        assert self.client.get("/api/users/@me/").json()["email"] == self.user.email

    def test_refresh_after_an_idle_impersonation_is_not_answered_by_its_timeout(self):
        self.mode = "enforce"
        binding_id, _ = self._impersonate()

        with time_machine.travel(timezone.now() + timedelta(minutes=31), tick=False):
            response = self.client.post("/dbsc/refresh", headers={protocol.SESSION_ID_HEADER: f'"{binding_id}"'})

        assert response.status_code == 403
        assert protocol.CHALLENGE_HEADER in response.headers

    def test_an_expired_impersonation_flag_leaves_no_bound_anonymous_session(self):
        binding_id, _ = self._impersonate()

        with time_machine.travel(timezone.now() + timedelta(days=3), tick=False):
            self.client.get("/insights")

        assert not Session.objects.filter(dbsc_binding__id=binding_id).exists()
