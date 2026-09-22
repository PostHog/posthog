import hmac

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.github.provider import CORE_CONSUMERS, SPECS, build_github_provider
from posthog.ingress.verify.schemes import VerificationOutcome

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
        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=INSTANCE_SECRET):
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
