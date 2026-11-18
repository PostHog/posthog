import hmac
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import jwt
from parameterized import parameterized

from posthog.credentials_service.test.test_settings_fallback import FLAG, POST, SERVICE_SETTINGS, _FakeResponse, _steady
from posthog.ingress.github import provider
from posthog.ingress.github.provider import CORE_CONSUMERS, SPECS, build_github_provider
from posthog.ingress.verify.schemes import VerificationOutcome
from posthog.jwt import PosthogJwtAudience

BODY = b'{"action":"created"}'
INSTANCE_SECRET = "posthog-app-secret"
STAMPHOG_SECRET = "stamphog-app-secret"


def _signature(secret: str) -> str:
    return "sha256=" + hmac.digest(secret.encode(), BODY, "sha256").hex()


@override_settings(STAMPHOG_GITHUB_APP_WEBHOOK_SECRET=STAMPHOG_SECRET)
class TestGitHubProvider(SimpleTestCase):
    @parameterized.expand(
        [
            ("posthog_app", "posthog", INSTANCE_SECRET, STAMPHOG_SECRET),
            ("stamphog_app", "stamphog", STAMPHOG_SECRET, INSTANCE_SECRET),
        ]
    )
    def test_each_app_only_accepts_its_own_secret(
        self, _name: str, app: str, own_secret: str, other_secret: str
    ) -> None:
        with patch("posthog.credentials_service.instance_settings.get_instance_setting", return_value=INSTANCE_SECRET):
            scheme = build_github_provider(app).scheme()

            self.assertEqual(
                scheme.verify(body=BODY, headers={"X-Hub-Signature-256": _signature(own_secret)}).outcome,
                VerificationOutcome.VERIFIED,
            )
            self.assertEqual(
                scheme.verify(body=BODY, headers={"X-Hub-Signature-256": _signature(other_secret)}).outcome,
                VerificationOutcome.INVALID,
            )

    def test_every_declared_app_has_a_spec_and_the_core_consumers_fit_it(self) -> None:
        self.assertEqual({spec.app for spec in SPECS}, {"posthog", "stamphog"})
        declared = {(spec.provider, spec.app): spec.event_types for spec in SPECS}
        # A shared superset would let a Stamphog consumer register for an event type that App
        # never receives, which is what the registry validation exists to refuse.
        self.assertLess(declared[("github", "stamphog")], declared[("github", "posthog")])
        for consumer in CORE_CONSUMERS:
            self.assertLessEqual(consumer.event_types, declared[(consumer.provider, consumer.app)])


@override_settings(**SERVICE_SETTINGS)
class TestGitHubWebhookSecretFromCredentialsService(SimpleTestCase):
    def setUp(self) -> None:
        for patcher in (patch(FLAG, return_value=True), patch("posthog.cache_utils.TEST", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        for getter in (provider._posthog_app_secret, provider._stamphog_app_secret):
            getter.clear_cache()
            self.addCleanup(getter.clear_cache)

    @parameterized.expand(
        [
            ("posthog_app", "posthog", "GITHUB_WEBHOOK_SECRET", "integrations"),
            ("stamphog_app", "stamphog", "STAMPHOG_GITHUB_APP_WEBHOOK_SECRET", "stamphog"),
        ]
    )
    def test_deliveries_verify_against_one_cached_service_read(
        self, _name: str, app: str, key: str, caller: str
    ) -> None:
        secret = f"{app}-secret-from-service"
        response = _FakeResponse({"secrets": {key: _steady(secret)}, "missing": []})
        scheme = build_github_provider(app).scheme()

        with patch(POST, return_value=response) as post:
            outcomes = [
                scheme.verify(body=BODY, headers={"X-Hub-Signature-256": _signature(secret)}).outcome for _ in range(3)
            ]

        self.assertEqual(outcomes, [VerificationOutcome.VERIFIED] * 3)
        self.assertEqual(post.call_count, 1)
        claims: dict[str, Any] = jwt.decode(
            post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer "),
            SERVICE_SETTINGS["CREDENTIALS_SERVICE_JWT_SECRET"],
            algorithms=["HS256"],
            audience=PosthogJwtAudience.CREDENTIALS_SERVICE.value,
        )
        self.assertEqual((claims["keys"], claims["caller"]), ([key], caller))
