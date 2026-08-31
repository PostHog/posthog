import json
import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest

from django.test import RequestFactory, override_settings

import jwt as pyjwt
from parameterized import parameterized
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import ScopedServiceJWTAuthentication
from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

TEST_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.RECORDING_API,
    settings_name="TEST_SCOPED_SERVICE_JWT_SECRET",
)

OTHER_AUDIENCE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.LIVESTREAM,
    settings_name="TEST_SCOPED_SERVICE_JWT_SECRET",
)


class TeamScopedAuthentication(ScopedServiceJWTAuthentication):
    purpose = TEST_PURPOSE


class FleetScopedAuthentication(ScopedServiceJWTAuthentication):
    purpose = TEST_PURPOSE
    require_team = False


def _raw_token(
    key: str, claims: dict, audience: str = PosthogJwtAudience.RECORDING_API.value, algorithm: str = "HS256"
) -> str:
    payload = {"aud": audience, "exp": datetime.now(tz=UTC) + timedelta(minutes=5), **claims}
    return pyjwt.encode(payload, key, algorithm=algorithm)


def _b64url(segment: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(segment).encode()).rstrip(b"=").decode()


# Assembled by hand because encoding alg=none through pyjwt would trip semgrep's none-alg audit
# rules, and an attacker forging one would not use our signing helpers anyway.
def _unsigned_alg_none_token(claims: dict, audience: str = PosthogJwtAudience.RECORDING_API.value) -> str:
    exp = int((datetime.now(tz=UTC) + timedelta(minutes=5)).timestamp())
    header = {"alg": "none", "typ": "JWT"}
    payload = {"aud": audience, "exp": exp, **claims}
    return f"{_b64url(header)}.{_b64url(payload)}."


@override_settings(TEST_SCOPED_SERVICE_JWT_SECRET="new-key,old-key")
class TestScopedServiceJwtPurpose(APIBaseTest):
    def test_mint_round_trips_claims_and_audience(self):
        token = TEST_PURPOSE.mint({"team_id": 123, "ticket_id": "abc"})

        claims = TEST_PURPOSE.verify(token)

        assert claims["team_id"] == 123
        assert claims["ticket_id"] == "abc"
        assert claims["aud"] == "posthog:recording_api"
        assert "exp" in claims

    def test_signs_with_newest_key_and_verifies_old_key_tokens(self):
        minted = TEST_PURPOSE.mint({"team_id": 1})
        pyjwt.decode(minted, "new-key", audience=TEST_PURPOSE.audience.value, algorithms=["HS256"])

        old_key_token = _raw_token("old-key", {"team_id": 1})
        assert TEST_PURPOSE.verify(old_key_token)["team_id"] == 1

    def test_wrong_audience_is_rejected(self):
        token = OTHER_AUDIENCE_PURPOSE.mint({"team_id": 1})
        with pytest.raises(pyjwt.InvalidAudienceError):
            TEST_PURPOSE.verify(token)

    @parameterized.expand(
        [
            ("alg_none_unsigned", lambda: _unsigned_alg_none_token({"team_id": 1})),
            ("hs512_signed_with_correct_key", lambda: _raw_token("new-key", {"team_id": 1}, algorithm="HS512")),
        ]
    )
    def test_tokens_not_signed_with_hs256_are_rejected(self, _name, make_token):
        with pytest.raises(pyjwt.InvalidAlgorithmError):
            TEST_PURPOSE.verify(make_token())

    @override_settings(TEST_SCOPED_SERVICE_JWT_SECRET=["list-new", "list-old"])
    def test_list_typed_settings_sign_with_first_and_verify_all(self):
        minted = TEST_PURPOSE.mint({"team_id": 1})
        pyjwt.decode(minted, "list-new", audience=TEST_PURPOSE.audience.value, algorithms=["HS256"])
        assert TEST_PURPOSE.verify(_raw_token("list-old", {"team_id": 1}))["team_id"] == 1

    @override_settings(TEST_SCOPED_SERVICE_JWT_SECRET="")
    def test_unprovisioned_purpose_is_disabled_and_refuses_to_mint(self):
        assert TEST_PURPOSE.enabled() is False
        with pytest.raises(RuntimeError):
            TEST_PURPOSE.mint({"team_id": 1})
        with pytest.raises(RuntimeError):
            TEST_PURPOSE.verify(_raw_token("any-key", {"team_id": 1}))


@override_settings(TEST_SCOPED_SERVICE_JWT_SECRET="new-key,old-key")
class TestScopedServiceJWTAuthentication(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.authentication = TeamScopedAuthentication()

    def _request(self, token: str | None, url_team_id: int | str | None = None) -> Request:
        if token is not None:
            django_request = self.factory.get("/internal/endpoint", HTTP_AUTHORIZATION=f"Bearer {token}")
        else:
            django_request = self.factory.get("/internal/endpoint")
        if url_team_id is not None:
            django_request.resolver_match = cast(Any, SimpleNamespace(kwargs={"team_id": str(url_team_id)}))
        return Request(django_request)  # ty: ignore[invalid-return-type]

    def _authenticate(self, authentication: ScopedServiceJWTAuthentication, request: Request) -> tuple[Any, Any]:
        result = authentication.authenticate(request)
        assert result is not None
        return result

    def test_valid_token_authenticates_as_the_token_team(self):
        token = TEST_PURPOSE.mint({"team_id": self.team.id})

        user, auth = self._authenticate(self.authentication, self._request(token, url_team_id=self.team.id))

        assert auth["team_id"] == self.team.id
        assert user.is_authenticated
        assert user.current_team_id == self.team.id
        assert user.current_organization_id == self.team.organization_id

    def test_token_for_another_team_cannot_reach_the_url_team(self):
        token = TEST_PURPOSE.mint({"team_id": self.team.id + 1})
        with pytest.raises(AuthenticationFailed):
            self.authentication.authenticate(self._request(token, url_team_id=self.team.id))

    @parameterized.expand(
        [
            ("expired", lambda self: TEST_PURPOSE.mint({"team_id": self.team.id}, ttl=timedelta(minutes=-1))),
            ("wrong_audience", lambda self: OTHER_AUDIENCE_PURPOSE.mint({"team_id": self.team.id})),
            ("wrong_key", lambda self: _raw_token("not-our-key", {"team_id": self.team.id})),
            ("garbage", lambda self: "not-a-jwt"),
            ("missing_team_claim", lambda self: TEST_PURPOSE.mint({"op": "read"})),
            ("nonexistent_team", lambda self: TEST_PURPOSE.mint({"team_id": 999999999})),
        ]
    )
    def test_bad_tokens_are_rejected(self, _name, make_token):
        with pytest.raises(AuthenticationFailed):
            self.authentication.authenticate(self._request(make_token(self)))

    def test_request_without_bearer_header_falls_through_to_other_authenticators(self):
        assert self.authentication.authenticate(self._request(None)) is None

    def test_non_utf8_bearer_value_is_a_clean_auth_failure(self):
        request = Request(self.factory.get("/internal/endpoint", HTTP_AUTHORIZATION="Bearer \xff\xfe"))
        with pytest.raises(AuthenticationFailed):
            self.authentication.authenticate(request)

    def test_failures_send_a_bearer_challenge_so_drf_renders_401_not_403(self):
        assert self.authentication.authenticate_header(self._request(None)) == "Bearer"

    @override_settings(TEST_SCOPED_SERVICE_JWT_SECRET="")
    def test_unconfigured_secret_fails_closed(self):
        token = _raw_token("any-key", {"team_id": self.team.id})
        with pytest.raises(AuthenticationFailed):
            self.authentication.authenticate(self._request(token))

    def test_fleet_scoped_purpose_authenticates_without_a_team(self):
        token = TEST_PURPOSE.mint({"op": "sweep"})

        user, _auth = self._authenticate(FleetScopedAuthentication(), self._request(token))

        assert user.is_authenticated
        assert user.current_team_id is None

    def test_fleet_scoped_purpose_still_binds_a_team_when_the_claim_is_present(self):
        token = TEST_PURPOSE.mint({"team_id": self.team.id})

        user, _auth = self._authenticate(FleetScopedAuthentication(), self._request(token))

        assert user.current_team_id == self.team.id
