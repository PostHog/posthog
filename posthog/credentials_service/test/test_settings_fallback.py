from typing import Any

import pytest
from unittest import mock

from django.test import SimpleTestCase, override_settings

import jwt
import requests
from parameterized import parameterized

from posthog.credentials_service import settings_fallback
from posthog.credentials_service.callers import CredentialsCaller
from posthog.credentials_service.errors import CredentialsServiceUnreachableError, SecretInRecoveryError
from posthog.jwt import PosthogJwtAudience

SERVICE_SETTINGS: dict[str, Any] = {
    "CREDENTIALS_SERVICE_URL": "http://credentials-service.credentials-service.svc.cluster.local",
    "CREDENTIALS_SERVICE_JWT_SECRET": "signing-key",
}

KEY = "GOOGLE_ADS_DEVELOPER_TOKEN"
OTHER = "GOOGLE_ADS_APP_CLIENT_ID"
CALLER = CredentialsCaller.INTEGRATIONS
FLAG = "posthog.credentials_service.client.posthoganalytics.feature_enabled"
POST = "posthog.credentials_service.client.internal_requests.post"


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def _steady(value: str) -> dict[str, Any]:
    return {"state": "steady", "value": value, "version_id": "v1", "fetched_at": "now"}


def _missing(*keys: str) -> _FakeResponse:
    return _FakeResponse({"secrets": {}, "missing": list(keys)})


def _keys_asked_for(authorization: str) -> list[str]:
    claims = jwt.decode(
        authorization.removeprefix("Bearer "),
        "signing-key",
        algorithms=["HS256"],
        audience=PosthogJwtAudience.CREDENTIALS_SERVICE.value,
    )
    return list(claims["keys"])


@override_settings(**SERVICE_SETTINGS)
class TestSettingsFallback(SimpleTestCase):
    def setUp(self) -> None:
        flag = mock.patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)
        settings_fallback.SETTINGS_FALLBACK_COUNTER.clear()

    def _count(self, outcome: str) -> float:
        return settings_fallback.SETTINGS_FALLBACK_COUNTER.labels(key=KEY, outcome=outcome)._value.get()

    @parameterized.expand(
        [
            # The service is live, so a call site whose key has not moved yet must keep working.
            ("still_in_settings", {KEY: "from-settings"}, None, "from-settings", "settings"),
            # Configured nowhere is what `settings.X` already returned: an empty string, not an error.
            ("configured_nowhere", {}, None, "", "unset"),
            # A caller with its own settings store (Slack instance settings) must not read Django's.
            ("custom_lookup_wins", {KEY: "django-copy"}, "instance-setting", "instance-setting", "settings"),
        ]
    )
    def test_a_key_not_in_the_service(
        self, _name: str, environ: dict[str, str], custom_value: str | None, expected: str, outcome: str
    ) -> None:
        kwargs: dict[str, Any] = {}
        if custom_value is not None:
            kwargs["settings_lookup"] = lambda key: custom_value

        with mock.patch(POST, return_value=_missing(KEY)):
            with mock.patch.dict("os.environ", environ, clear=True):
                with mock.patch.object(settings_fallback, "logger") as log:
                    assert settings_fallback.get_or_settings(KEY, CALLER, **kwargs) == expected

        assert self._count(outcome) == 1
        # Only a value still in settings is a rollout gap, so only that one is counted and logged as one.
        other_outcome = "unset" if outcome == "settings" else "settings"
        assert self._count(other_outcome) == 0
        if outcome == "settings":
            assert log.warning.call_args.kwargs["key"] == KEY

    # A key the service holds is read from the service, not from the environment it also still sits
    # in. Otherwise the migration would look complete while changing nothing.
    def test_the_service_wins_over_a_value_still_in_settings(self) -> None:
        with mock.patch(POST, return_value=_FakeResponse({"secrets": {KEY: _steady("from-service")}, "missing": []})):
            with mock.patch.dict("os.environ", {KEY: "stale-copy"}):
                assert settings_fallback.get_or_settings(KEY, CALLER) == "from-service"

        assert self._count("settings") == 0

    @parameterized.expand(
        [
            # Recovery means the credential is known-burned. The settings copy is the burned value, so
            # falling back would turn the kill switch into a no-op.
            (
                "recovery",
                {"return_value": _FakeResponse({"secrets": {KEY: {"state": "recovery"}}, "missing": []})},
                SecretInRecoveryError,
            ),
            # An outage is not a rollout gap: there is no last known good to fall back to.
            ("unreachable", {"side_effect": requests.ConnectionError("refused")}, CredentialsServiceUnreachableError),
        ]
    )
    def test_does_not_fall_back(self, _name: str, post: dict[str, Any], error: type[Exception]) -> None:
        for read in (
            lambda: settings_fallback.get_or_settings(KEY, CALLER),
            lambda: settings_fallback.get_many_or_settings([KEY, OTHER], CALLER),
        ):
            with mock.patch(POST, **post):
                with mock.patch.dict("os.environ", {KEY: "still-in-settings", OTHER: "still-in-settings"}):
                    with pytest.raises(error):
                        read()

        assert self._count("settings") == 0

    # A part-migrated batch is the normal state during the rollout: the batch can't say which key was
    # missing, so it re-resolves per key and each one takes the path it needs.
    def test_a_batch_with_one_missing_key_resolves_the_rest_per_key(self) -> None:
        def post(*args: Any, **kwargs: Any) -> _FakeResponse:
            asked = _keys_asked_for(kwargs["headers"]["Authorization"])
            if asked == [OTHER]:
                return _FakeResponse({"secrets": {OTHER: _steady("from-service")}, "missing": []})
            return _FakeResponse({"secrets": {OTHER: _steady("from-service")}, "missing": [KEY]})

        with mock.patch(POST, side_effect=post) as mock_post:
            with mock.patch.dict("os.environ", {KEY: "still-in-settings"}):
                assert settings_fallback.get_many_or_settings([KEY, OTHER], CALLER) == {
                    KEY: "still-in-settings",
                    OTHER: "from-service",
                }

        assert mock_post.call_count == 3
        assert self._count("settings") == 1

    def test_a_complete_batch_is_one_request(self) -> None:
        payload = {"secrets": {KEY: _steady("a"), OTHER: _steady("b")}, "missing": []}
        with mock.patch(POST, return_value=_FakeResponse(payload)) as mock_post:
            assert settings_fallback.get_many_or_settings([KEY, OTHER], CALLER) == {KEY: "a", OTHER: "b"}

        assert mock_post.call_count == 1
        assert _keys_asked_for(mock_post.call_args.kwargs["headers"]["Authorization"]) == sorted([KEY, OTHER])
