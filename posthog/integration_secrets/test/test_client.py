import os
from typing import Any

import pytest
from unittest import mock
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import jwt
import requests
from parameterized import parameterized

from posthog.integration_secrets.callers import IntegrationCaller
from posthog.integration_secrets.client import (
    IntegrationSecretsClient,
    integration_service_enabled,
    integration_service_signing_keys,
)
from posthog.integration_secrets.errors import (
    IntegrationSecretsFailure,
    IntegrationServiceMisconfiguredError,
    IntegrationServiceUnreachableError,
    SecretInRecoveryError,
    SecretMissingError,
)
from posthog.jwt import PosthogJwtAudience

SERVICE_SETTINGS: dict[str, Any] = {
    "INTEGRATION_SERVICE_URL": "http://integration-service.posthog.svc.cluster.local",
    "INTEGRATION_SERVICE_JWT_SECRET": "signing-key-new,signing-key-old",
}

KEY = "HUBSPOT_APP_CLIENT_SECRET"
CALLER = IntegrationCaller.WAREHOUSE_SOURCES

FLAG = "posthog.integration_secrets.client.posthoganalytics.feature_enabled"
POST = "posthog.integration_secrets.client.internal_requests.post"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def body(secrets: dict[str, Any] | None = None, missing: list[str] | None = None) -> dict[str, Any]:
    return {"secrets": secrets or {}, "missing": missing or []}


def steady(value: str) -> dict[str, Any]:
    return {"state": "steady", "value": value, "version_id": "v1", "fetched_at": "now"}


@override_settings(**SERVICE_SETTINGS)
class TestIntegrationSecretsClient(SimpleTestCase):
    def setUp(self) -> None:
        self.secrets = IntegrationSecretsClient()
        flag = patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def test_returns_the_value_the_service_resolved(self) -> None:
        with patch(POST, return_value=FakeResponse(body({KEY: steady("sec")}))):
            assert self.secrets.get(KEY, CALLER) == "sec"

    # No cache anywhere: a rotation has to land on the very next read, and the service's
    # "safe to retire the old value" verdict depends on nobody holding a stale copy.
    def test_reads_the_service_every_time(self) -> None:
        responses = [FakeResponse(body({KEY: steady("old")})), FakeResponse(body({KEY: steady("new")}))]
        with patch(POST, side_effect=responses) as post:
            assert self.secrets.get(KEY, CALLER) == "old"
            assert self.secrets.get(KEY, CALLER) == "new"
            assert post.call_count == 2

    def test_batches_several_keys_into_one_request(self) -> None:
        keys = [KEY, "HUBSPOT_APP_CLIENT_ID"]
        with patch(POST, return_value=FakeResponse(body({k: steady(f"v-{k}") for k in keys}))) as post:
            assert self.secrets.get_many(keys, CALLER) == {k: f"v-{k}" for k in keys}
            assert post.call_count == 1

    @parameterized.expand(
        [
            ("missing", {"missing": [KEY]}, SecretMissingError),
            ("absent from the response", {}, SecretMissingError),
        ]
    )
    def test_raises_a_typed_error_for(self, _name: str, response: dict[str, Any], expected: type[Exception]) -> None:
        with patch(POST, return_value=FakeResponse(body(**response))):
            with pytest.raises(expected):
                self.secrets.get(KEY, CALLER)

    # Platform client ids and secrets are what authenticate us to the third party, so a
    # burned one cannot be "reconnected" by a user — the integration is down until an
    # engineer re-provisions it. Failing immediately keeps that distinguishable from a
    # third-party outage.
    def test_recovery_raises_rather_than_returning_a_dead_credential(self) -> None:
        payload = {"state": "recovery", "version_id": "v1", "fetched_at": "now"}
        with patch(POST, return_value=FakeResponse(body({KEY: payload}))):
            with pytest.raises(SecretInRecoveryError):
                self.secrets.get(KEY, CALLER)

    def test_get_with_incoming_exposes_the_staged_value_during_a_rotation(self) -> None:
        # The wire still calls it `previous`; it carries the value a rotation has STAGED, which the
        # service accepts but has not made live. A caller retries with it when the provider has
        # already been rotated — not to reach an older value, which is not served at all.
        rotating = {"state": "rotating", "value": "live", "previous": "staged", "version_id": "v1", "fetched_at": "now"}
        with patch(POST, return_value=FakeResponse(body({KEY: rotating}))):
            secret = self.secrets.get_with_incoming(KEY, CALLER)
        assert secret.current == "live"
        assert secret.incoming == "staged"

    # The 503 contract: the service answers 503 rather than all-missing on a cold start,
    # and only raise_for_status keeps that from surfacing as SecretMissingError, which
    # callers treat as terminal.
    def test_a_service_error_status_propagates_rather_than_reading_as_missing(self) -> None:
        class ErrorResponse:
            def raise_for_status(self) -> None:
                raise requests.HTTPError("503 Server Error", response=requests.Response())

            def json(self) -> dict[str, Any]:
                return {"error": "Secret store unavailable"}

        with patch(POST, return_value=ErrorResponse()):
            with pytest.raises(IntegrationServiceUnreachableError):
                self.secrets.get(KEY, CALLER)

    # No `requests` exception may escape, whatever the status. A caller is mid-conversation with
    # some third party, so a bare HTTPError from here is indistinguishable from one that API
    # raised — and callers act on that difference. The 404 is the case that bites: a misrouted
    # INTEGRATION_SERVICE_URL is our deploy error, but a caller seeing a raw 404 reads it as the
    # user's endpoint being gone and can stop their work over it.
    @parameterized.expand(
        [
            ("404 misrouted url", requests.HTTPError("404 Client Error", response=requests.Response())),
            ("401 unaccepted signing key", requests.HTTPError("401 Unauthorized", response=requests.Response())),
            ("connection refused", requests.ConnectionError("connection refused")),
            ("read timeout", requests.Timeout("timed out")),
        ]
    )
    def test_transport_failure_wears_this_clients_type_for(self, _name: str, raised: Exception) -> None:
        class ErrorResponse:
            def raise_for_status(self) -> None:
                raise raised

            def json(self) -> dict[str, Any]:
                return {}

        # Raised from the call itself for a connection failure, from raise_for_status for a status.
        side_effect = raised if isinstance(raised, requests.ConnectionError | requests.Timeout) else None
        patched = patch(POST, side_effect=side_effect) if side_effect else patch(POST, return_value=ErrorResponse())
        with patched:
            with pytest.raises(IntegrationServiceUnreachableError) as exc_info:
                self.secrets.get(KEY, CALLER)
        # The cause is kept so error tracking and logs still show what actually went wrong.
        assert exc_info.value.__cause__ is raised
        assert not isinstance(exc_info.value, requests.RequestException)

    # A body that isn't JSON is the same class of failure as no answer at all: something is
    # between us and the service, or the service is broken. It must not surface as a missing key.
    def test_an_unparseable_body_is_unreachable_not_missing(self) -> None:
        class HtmlResponse:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

        with patch(POST, return_value=HtmlResponse()):
            with pytest.raises(IntegrationServiceUnreachableError):
                self.secrets.get(KEY, CALLER)

    # With no cache there is no last known good, so an outage is an outage. This is the
    # trade for immediate rotations, and it is why the service needs an availability SLO
    # before the environment variables come out.
    def test_an_unreachable_service_raises_rather_than_serving_something_stale(self) -> None:
        with patch(POST, return_value=FakeResponse(body({KEY: steady("sec")}))):
            self.secrets.get(KEY, CALLER)

        with patch(POST, side_effect=requests.ConnectionError("integration service is down")):
            with pytest.raises(IntegrationServiceUnreachableError):
                self.secrets.get(KEY, CALLER)

    def test_does_not_fall_back_to_the_environment_when_the_service_is_down(self) -> None:
        with (
            patch(POST, side_effect=requests.ConnectionError("integration service is down")),
            patch.dict("os.environ", {KEY: "from-env"}),
        ):
            with pytest.raises(IntegrationServiceUnreachableError):
                self.secrets.get(KEY, CALLER)

    # The base type is the whole contract a caller depends on: catch one thing, and a subclass
    # added later is covered without every call site being revisited.
    @parameterized.expand(
        [
            ("missing", SecretMissingError(KEY), True),
            ("in recovery", SecretInRecoveryError(KEY), False),
            ("half-configured", IntegrationServiceMisconfiguredError("INTEGRATION_SERVICE_URL"), True),
            ("unreachable", IntegrationServiceUnreachableError("no answer"), False),
        ]
    )
    def test_every_failure_shares_the_base_type_and_declares_reportability(
        self, _name: str, error: Exception, reportable: bool
    ) -> None:
        assert isinstance(error, IntegrationSecretsFailure)
        assert error.reportable is reportable


@override_settings(**SERVICE_SETTINGS)
class TestRolloutFlag(SimpleTestCase):
    def setUp(self) -> None:
        self.secrets = IntegrationSecretsClient()

    def test_reads_the_environment_while_the_flag_is_off(self) -> None:
        with (
            patch(FLAG, return_value=False),
            patch(POST) as post,
            patch.dict("os.environ", {KEY: "from-env"}),
        ):
            assert self.secrets.get(KEY, CALLER) == "from-env"
            post.assert_not_called()

    # Closed means the old path, not a failed read. A flag service blip must not take out
    # credential reads while the environment variables are still in place.
    def test_a_failing_flag_check_falls_back_to_the_environment(self) -> None:
        with (
            patch(FLAG, side_effect=RuntimeError("flag service unavailable")),
            patch(POST) as post,
            patch.dict("os.environ", {KEY: "from-env"}),
        ):
            assert self.secrets.get(KEY, CALLER) == "from-env"
            post.assert_not_called()

    @parameterized.expand(
        [
            ("both unset", "", "", True, False),
            ("url only", "http://svc", "", True, False),
            ("key only", "", "key", True, False),
            ("configured but flag off", "http://svc", "key", False, False),
            ("configured and flag on", "http://svc", "key", True, True),
        ]
    )
    def test_enabled_requires_url_key_and_flag(
        self, _name: str, url: str, key: str, flag: bool, expected: bool
    ) -> None:
        with (
            override_settings(INTEGRATION_SERVICE_URL=url, INTEGRATION_SERVICE_JWT_SECRET=key),
            patch(FLAG, return_value=flag),
        ):
            assert integration_service_enabled() is expected


class TestUnconfigured(SimpleTestCase):
    """Self-hosted and local dev: no service, read the environment exactly as before."""

    @override_settings(INTEGRATION_SERVICE_URL="", INTEGRATION_SERVICE_JWT_SECRET="")
    def test_raises_when_unconfigured_and_the_environment_has_nothing_either(self) -> None:
        with pytest.raises(SecretMissingError):
            IntegrationSecretsClient().get("A_KEY_NOBODY_SET", CALLER)

    @override_settings(INTEGRATION_SERVICE_URL="", INTEGRATION_SERVICE_JWT_SECRET="")
    def test_the_error_says_the_service_was_never_called(self) -> None:
        # "not available from the integration service" sends the reader to look for a key that is
        # sitting in the service already. The reason it did not resolve is that nothing asked.
        with pytest.raises(SecretMissingError) as excinfo:
            IntegrationSecretsClient().get("A_KEY_NOBODY_SET", CALLER)
        assert "was not called" in str(excinfo.value)
        assert "unconfigured" in str(excinfo.value)


class TestHalfConfigured(SimpleTestCase):
    """One variable without the other: refuse, rather than silently reading the environment."""

    @parameterized.expand(
        [
            ("url without a signing key", "http://svc", "", "INTEGRATION_SERVICE_JWT_SECRET"),
            ("signing key without a url", "", "signing-key", "INTEGRATION_SERVICE_URL"),
        ]
    )
    def test_raises_naming_the_variable_still_needed(self, _name: str, url: str, key: str, missing: str) -> None:
        with (
            override_settings(INTEGRATION_SERVICE_URL=url, INTEGRATION_SERVICE_JWT_SECRET=key),
            patch(POST) as post,
            patch(FLAG, return_value=True),
        ):
            with pytest.raises(IntegrationServiceMisconfiguredError) as excinfo:
                IntegrationSecretsClient().get(KEY, CALLER)
            assert missing in str(excinfo.value)
            post.assert_not_called()

    @override_settings(INTEGRATION_SERVICE_URL="http://svc", INTEGRATION_SERVICE_JWT_SECRET="")
    def test_a_mounted_environment_variable_does_not_paper_over_it(self) -> None:
        # The failure this exists to catch. Half-configured, the fallback would have returned the
        # value from the pod's environment and the deployment would look wired up — until someone
        # asks for a credential that only exists in the service.
        with patch.dict(os.environ, {KEY: "still-mounted-on-the-pod"}):
            with pytest.raises(IntegrationServiceMisconfiguredError):
                IntegrationSecretsClient().get(KEY, CALLER)

    @override_settings(INTEGRATION_SERVICE_URL="http://svc", INTEGRATION_SERVICE_JWT_SECRET="")
    def test_the_flag_does_not_rescue_a_half_configured_deployment(self) -> None:
        # Turning the flag off is how you disable the client deliberately; it is not a way to make
        # a misconfiguration legal, or the rollout gate would hide it.
        with patch(FLAG, return_value=False):
            with pytest.raises(IntegrationServiceMisconfiguredError):
                IntegrationSecretsClient().get(KEY, CALLER)


@override_settings(**SERVICE_SETTINGS)
class TestMintedToken(SimpleTestCase):
    """The token IS the request — there is no body, so these claims are the whole scope."""

    def setUp(self) -> None:
        self.secrets = IntegrationSecretsClient()
        flag = patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def _claims_from_call(self, post: Any) -> dict[str, Any]:
        header = post.call_args.kwargs["headers"]["Authorization"]
        return jwt.decode(
            header.removeprefix("Bearer "),
            integration_service_signing_keys()[0],
            audience=PosthogJwtAudience.INTEGRATION_SERVICE.value,
            algorithms=["HS256"],
        )

    def test_carries_only_the_keys_this_call_needs(self) -> None:
        with patch(POST, return_value=FakeResponse(body({KEY: steady("sec")}))) as post:
            self.secrets.get(KEY, CALLER)
            claims = self._claims_from_call(post)

        assert claims["keys"] == [KEY]
        assert claims["aud"] == PosthogJwtAudience.INTEGRATION_SERVICE.value

    # Attribution, not authorization: the service records it but grants nothing on it.
    def test_names_the_product_that_asked_rather_than_the_pod(self) -> None:
        with patch(POST, return_value=FakeResponse(body({KEY: steady("sec")}))) as post:
            self.secrets.get(KEY, IntegrationCaller.CDP)
            assert self._claims_from_call(post)["caller"] == "cdp"

    def test_signs_with_the_newest_key_so_rotation_is_zero_downtime(self) -> None:
        with patch(POST, return_value=FakeResponse(body({KEY: steady("sec")}))) as post:
            self.secrets.get(KEY, CALLER)
            token = post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")

        audience = PosthogJwtAudience.INTEGRATION_SERVICE.value
        jwt.decode(token, "signing-key-new", audience=audience, algorithms=["HS256"])
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, "signing-key-old", audience=audience, algorithms=["HS256"])


@override_settings(**SERVICE_SETTINGS)
class TestResolveLogging(SimpleTestCase):
    """The credential read is otherwise the one invisible hop in a job's HTTP traffic."""

    def setUp(self) -> None:
        self.secrets = IntegrationSecretsClient()
        flag = patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    @staticmethod
    def _response(payload: dict[str, Any], status_code: int = 200) -> Any:
        response = FakeResponse(payload)
        response.status_code = status_code  # type: ignore[attr-defined]
        return response

    def test_logs_the_request_with_the_shared_http_field_names(self) -> None:
        # Same names as data_imports.http.request, so a credential read shows up in the same
        # query as the rest of a job's traffic rather than needing its own.
        with patch(POST, return_value=self._response(body({KEY: steady("sec")}))):
            with patch("posthog.integration_secrets.client.logger") as log:
                self.secrets.get(KEY, CALLER)

        fields = log.debug.call_args.kwargs
        assert log.debug.call_args.args[0] == "integration_secrets.resolve"
        assert fields["method"] == "POST"
        assert fields["status_code"] == 200
        assert fields["host"] == "integration-service.posthog.svc.cluster.local"
        assert fields["error_class"] is None
        assert fields["caller"] == str(CALLER)
        assert fields["keys"] == [KEY]
        assert isinstance(fields["latency_ms"], int)

    # The rotation questions this exists to answer: which value did this pod get, and has it
    # changed? Nothing about the value itself may be logged, so state and version carry it.
    def test_logs_per_key_state_and_version_at_info_when_a_rotation_is_in_flight(self) -> None:
        rotating = {
            "state": "rotating",
            "value": "live",
            "previous": "staged",
            "version_id": "v9",
            "fetched_at": "now",
        }
        with patch(POST, return_value=self._response(body({KEY: rotating}))):
            with patch("posthog.integration_secrets.client.logger") as log:
                self.secrets.get(KEY, CALLER)

        # info, not debug: a value changing under a caller that did nothing differently is the
        # thing you want visible without having turned debug on first.
        log.debug.assert_not_called()
        fields = log.info.call_args.kwargs
        assert fields["states"] == {KEY: "rotating"}
        assert fields["version_ids"] == {KEY: "v9"}

    @parameterized.expand(
        [
            ("a missing key", {"missing": [KEY]}, SecretMissingError),
            (
                "a key in recovery",
                {"secrets": {KEY: {"state": "recovery", "version_id": "v1", "fetched_at": "now"}}},
                SecretInRecoveryError,
            ),
        ]
    )
    def test_logs_at_info_for(self, _name: str, payload: dict[str, Any], expected: type[Exception]) -> None:
        with patch(POST, return_value=self._response(body(**payload))):
            with patch("posthog.integration_secrets.client.logger") as log:
                with pytest.raises(expected):
                    self.secrets.get(KEY, CALLER)

        log.info.assert_called_once()
        log.debug.assert_not_called()

    def test_logs_a_transport_failure_at_warning_with_the_error_class(self) -> None:
        with patch(POST, side_effect=requests.ConnectionError("connection refused")):
            with patch("posthog.integration_secrets.client.logger") as log:
                with pytest.raises(IntegrationServiceUnreachableError):
                    self.secrets.get(KEY, CALLER)

        fields = log.warning.call_args.kwargs
        assert fields["error_class"] == "ConnectionError"
        assert fields["status_code"] is None

    # The property that matters most here, and the reason nothing is scrubbed: fields are chosen
    # by name from the response, and no value field is among them. A scrubber would be a thing to
    # get wrong; selecting is a thing that cannot be.
    def test_no_credential_value_can_reach_a_log_line(self) -> None:
        secret_value = "sk-live-do-not-log-me"
        rotating = {
            "state": "rotating",
            "value": secret_value,
            "previous": "staged-do-not-log-me",
            "version_id": "v1",
            "fetched_at": "now",
        }
        with patch(POST, return_value=self._response(body({KEY: rotating}))):
            with patch("posthog.integration_secrets.client.logger") as log:
                assert self.secrets.get(KEY, CALLER) == secret_value

        emitted = repr([c.kwargs for c in log.info.call_args_list + log.debug.call_args_list])
        assert secret_value not in emitted
        assert "staged-do-not-log-me" not in emitted
        # The bearer token lives in a header the logger never touches.
        assert "Authorization" not in emitted
        assert "signing-key-new" not in emitted

    def test_a_broken_logger_cannot_fail_a_credential_read(self) -> None:
        # Same contract as the warehouse observer: telemetry must never become an outage.
        with patch(POST, return_value=self._response(body({KEY: steady("sec")}))):
            with patch("posthog.integration_secrets.client.logger") as log:
                log.debug.side_effect = [RuntimeError("log pipeline is down"), None]
                assert self.secrets.get(KEY, CALLER) == "sec"


@override_settings(**SERVICE_SETTINGS)
class TestInjectedSession(SimpleTestCase):
    def setUp(self) -> None:
        flag = patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    # Warehouse sources already meter and log every outbound request through a tracked adapter.
    # Passing that session in puts credential reads in the same place as the rest of the job's
    # traffic, instead of leaving a silent gap where the read was.
    def test_uses_the_session_it_was_given(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = FakeResponse(body({KEY: steady("sec")}))

        with patch(POST) as shared_post:
            assert IntegrationSecretsClient(session=session).get(KEY, CALLER) == "sec"

        session.post.assert_called_once()
        shared_post.assert_not_called()

    def test_defaults_to_the_shared_internal_session(self) -> None:
        with patch(POST, return_value=FakeResponse(body({KEY: steady("sec")}))) as shared_post:
            assert IntegrationSecretsClient().get(KEY, CALLER) == "sec"
        shared_post.assert_called_once()
