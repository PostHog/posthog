from typing import Any

import pytest
from unittest.mock import patch

from django.test import TestCase, override_settings

import jwt
from parameterized import parameterized

from posthog.integration_secrets.client import (
    IntegrationSecretsClient,
    integration_service_enabled,
    integration_service_signing_keys,
)
from posthog.integration_secrets.errors import SecretDeniedError, SecretInRecoveryError, SecretMissingError
from posthog.jwt import PosthogJwtAudience

SERVICE_SETTINGS: dict[str, Any] = {
    "INTEGRATION_SERVICE_URL": "http://integration-service.posthog.svc.cluster.local",
    "INTEGRATION_SERVICE_JWT_SECRET": "signing-key-new,signing-key-old",
    "INTEGRATION_SERVICE_CALLER": "posthog-django",
}

KEY = "HUBSPOT_APP_CLIENT_SECRET"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def body(
    secrets: dict[str, Any] | None = None,
    denied: list[str] | None = None,
    missing: list[str] | None = None,
    max_age: int = 60,
) -> dict[str, Any]:
    return {
        "secrets": secrets or {},
        "denied": denied or [],
        "missing": missing or [],
        "max_age_seconds": max_age,
    }


def steady(value: str) -> dict[str, Any]:
    return {"state": "steady", "value": value, "version_id": "v1", "fetched_at": "now"}


@override_settings(**SERVICE_SETTINGS)
class TestIntegrationSecretsClient(TestCase):
    def setUp(self) -> None:
        self.secrets = IntegrationSecretsClient()

    def test_returns_the_value_the_service_resolved(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body({KEY: steady("sec")})),
        ):
            assert self.secrets.get(KEY) == "sec"

    def test_caches_within_max_age_so_a_second_read_makes_no_request(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body({KEY: steady("sec")})),
        ) as post:
            self.secrets.get(KEY)
            self.secrets.get(KEY)
            assert post.call_count == 1

    def test_a_zero_max_age_disables_caching_so_a_rotation_lands_immediately(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            side_effect=[
                FakeResponse(body({KEY: steady("old")}, max_age=0)),
                FakeResponse(body({KEY: steady("new")}, max_age=0)),
            ],
        ) as post:
            assert self.secrets.get(KEY) == "old"
            assert self.secrets.get(KEY) == "new"
            assert post.call_count == 2

    def test_batches_several_keys_into_one_request(self) -> None:
        keys = [KEY, "HUBSPOT_APP_CLIENT_ID"]
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body({k: steady(f"v-{k}") for k in keys})),
        ) as post:
            assert self.secrets.get_many(keys) == {k: f"v-{k}" for k in keys}
            assert post.call_count == 1

    @parameterized.expand(
        [
            ("denied", {"denied": [KEY]}, SecretDeniedError),
            ("missing", {"missing": [KEY]}, SecretMissingError),
            ("absent from the response", {}, SecretMissingError),
        ]
    )
    def test_raises_a_typed_error_for(self, _name: str, response: dict[str, Any], expected: type[Exception]) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body(**response)),
        ):
            with pytest.raises(expected):
                self.secrets.get(KEY)

    def test_recovery_raises_rather_than_returning_a_credential_that_cannot_work(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body({KEY: {"state": "recovery", "version_id": "v1", "fetched_at": "now"}})),
        ):
            with pytest.raises(SecretInRecoveryError):
                self.secrets.get(KEY)

    def test_get_with_previous_exposes_the_outgoing_value_during_a_rotation(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(
                body(
                    {
                        KEY: {
                            "state": "rotating",
                            "value": "new",
                            "previous": "old",
                            "version_id": "v1",
                            "fetched_at": "now",
                        }
                    }
                )
            ),
        ):
            assert self.secrets.get_with_previous(KEY) == ("new", "old")


@override_settings(**SERVICE_SETTINGS)
class TestDegradation(TestCase):
    """A transient service failure must not fail a warehouse sync."""

    def setUp(self) -> None:
        self.secrets = IntegrationSecretsClient()

    def test_serves_the_last_known_good_value_when_the_service_becomes_unreachable(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            side_effect=[
                FakeResponse(body({KEY: steady("sec")}, max_age=0)),
                ConnectionError("integration service is down"),
            ],
        ):
            assert self.secrets.get(KEY) == "sec"
            assert self.secrets.get(KEY) == "sec"

    def test_falls_back_to_the_environment_when_unreachable_with_a_cold_cache(self) -> None:
        with (
            patch(
                "posthog.integration_secrets.client.internal_requests.post",
                side_effect=ConnectionError("integration service is down"),
            ),
            patch.dict("os.environ", {KEY: "from-env"}),
        ):
            assert self.secrets.get(KEY) == "from-env"

    # A denial is a configuration error, not a blip. Falling back to the environment
    # there would quietly restore exactly the access the allowlist just refused.
    def test_a_denial_propagates_instead_of_falling_back_to_the_environment(self) -> None:
        with (
            patch(
                "posthog.integration_secrets.client.internal_requests.post",
                return_value=FakeResponse(body(denied=[KEY])),
            ),
            patch.dict("os.environ", {KEY: "from-env"}),
        ):
            with pytest.raises(SecretDeniedError):
                self.secrets.get(KEY)


class TestUnconfigured(TestCase):
    """Self-hosted and local dev: no service, read the environment exactly as before."""

    def setUp(self) -> None:
        self.secrets = IntegrationSecretsClient()

    @override_settings(INTEGRATION_SERVICE_URL="", INTEGRATION_SERVICE_JWT_SECRET="key")
    def test_reads_the_environment_when_no_url_is_configured(self) -> None:
        with (
            patch("posthog.integration_secrets.client.internal_requests.post") as post,
            patch.dict("os.environ", {KEY: "from-env"}),
        ):
            assert self.secrets.get(KEY) == "from-env"
            post.assert_not_called()

    @override_settings(INTEGRATION_SERVICE_URL="http://svc", INTEGRATION_SERVICE_JWT_SECRET="")
    def test_reads_the_environment_when_no_signing_key_is_configured(self) -> None:
        with (
            patch("posthog.integration_secrets.client.internal_requests.post") as post,
            patch.dict("os.environ", {KEY: "from-env"}),
        ):
            assert self.secrets.get(KEY) == "from-env"
            post.assert_not_called()

    @override_settings(INTEGRATION_SERVICE_URL="", INTEGRATION_SERVICE_JWT_SECRET="")
    def test_raises_when_unconfigured_and_the_environment_has_nothing_either(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            with pytest.raises(SecretMissingError):
                self.secrets.get("A_KEY_NOBODY_SET")

    @parameterized.expand(
        [
            ("both unset", "", "", False),
            ("url only", "http://svc", "", False),
            ("key only", "", "key", False),
            ("both set", "http://svc", "key", True),
        ]
    )
    def test_enabled_requires_both_url_and_key(self, _name: str, url: str, key: str, expected: bool) -> None:
        with override_settings(INTEGRATION_SERVICE_URL=url, INTEGRATION_SERVICE_JWT_SECRET=key):
            assert integration_service_enabled() is expected


@override_settings(**SERVICE_SETTINGS)
class TestMintedToken(TestCase):
    """The token IS the request — there is no body, so these claims are the whole scope."""

    def setUp(self) -> None:
        self.secrets = IntegrationSecretsClient()

    def _claims_from_call(self, post: Any) -> dict[str, Any]:
        header = post.call_args.kwargs["headers"]["Authorization"]
        return jwt.decode(
            header.removeprefix("Bearer "),
            integration_service_signing_keys()[0],
            audience=PosthogJwtAudience.INTEGRATION_SERVICE.value,
            algorithms=["HS256"],
        )

    def test_carries_only_the_keys_this_call_needs(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body({KEY: steady("sec")})),
        ) as post:
            self.secrets.get(KEY)
            claims = self._claims_from_call(post)

        assert claims["keys"] == [KEY]
        assert claims["caller"] == "posthog-django"
        assert claims["aud"] == PosthogJwtAudience.INTEGRATION_SERVICE.value

    def test_signs_with_the_newest_key_so_rotation_is_zero_downtime(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body({KEY: steady("sec")})),
        ) as post:
            self.secrets.get(KEY)
            header = post.call_args.kwargs["headers"]["Authorization"]

        # Verifies under the new key, and not under the retired one.
        jwt.decode(
            header.removeprefix("Bearer "),
            "signing-key-new",
            audience=PosthogJwtAudience.INTEGRATION_SERVICE.value,
            algorithms=["HS256"],
        )
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(
                header.removeprefix("Bearer "),
                "signing-key-old",
                audience=PosthogJwtAudience.INTEGRATION_SERVICE.value,
                algorithms=["HS256"],
            )

    def test_omits_previous_used_when_nothing_has_been_reported(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body({KEY: steady("sec")})),
        ) as post:
            self.secrets.get(KEY)
            assert "previous_used" not in self._claims_from_call(post)

    # This report is the only way the service can tell "the rotation has landed" apart
    # from "nothing is reading this credential" — see safeToRetirePrevious.
    def test_reports_previous_used_on_the_next_request_then_stops(self) -> None:
        with patch(
            "posthog.integration_secrets.client.internal_requests.post",
            return_value=FakeResponse(body({KEY: steady("sec")}, max_age=0)),
        ) as post:
            self.secrets.get(KEY)
            self.secrets.report_previous_used(KEY)
            self.secrets.get(KEY)
            assert self._claims_from_call(post)["previous_used"] == [KEY]

            self.secrets.get(KEY)
            assert "previous_used" not in self._claims_from_call(post)
