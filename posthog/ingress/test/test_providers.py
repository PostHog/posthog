from collections.abc import Callable, Mapping
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.ingress.github.provider import build_github_provider
from posthog.ingress.mailgun.provider import build_mailgun_provider
from posthog.ingress.providers import UnknownApp, WebhookProvider
from posthog.ingress.slack.provider import build_slack_provider
from posthog.ingress.sns.provider import build_sns_provider


def _github(app: str) -> WebhookProvider:
    return build_github_provider(app)


def _mailgun(app: str) -> WebhookProvider:
    return build_mailgun_provider(app, signing_key_getter=lambda: "signing-key")


def _slack(app: str) -> WebhookProvider:
    return build_slack_provider(secret_getter=lambda: "signing-secret", app=app)


def _verified(message: Mapping[str, Any]) -> bool:
    return True


def _no_topics() -> frozenset[str]:
    return frozenset()


def _sns(app: str) -> WebhookProvider:
    return build_sns_provider(verify_message=_verified, allowed_topic_arns=_no_topics, app=app)


# One row per builder that takes an app name: the provider, the builder, a declared app, and a
# plausible typo of one.
BUILDERS = [
    ("github", _github, "posthog", "gitlab"),
    ("mailgun", _mailgun, "inbound", "events"),
    ("slack", _slack, "supporthog", "supporthog_events"),
    ("sns", _sns, "default", "defaults"),
]


class TestProviderAppNames(SimpleTestCase):
    @parameterized.expand(BUILDERS)
    def test_an_unknown_app_is_refused_at_build(
        self, provider: str, builder: Callable[[str], WebhookProvider], declared_app: str, unknown_app: str
    ) -> None:
        # Without this the endpoint builds and serves: consumers register against the declared
        # app names, so nothing matches the typo and every delivery is receipted and dropped.
        with self.assertRaises(UnknownApp) as caught:
            builder(unknown_app)

        message = str(caught.exception)
        self.assertIn(provider, message)
        self.assertIn(unknown_app, message)
        self.assertIn(declared_app, message)

    @parameterized.expand(BUILDERS)
    def test_a_declared_app_builds(
        self, _provider: str, builder: Callable[[str], WebhookProvider], declared_app: str, _unknown_app: str
    ) -> None:
        self.assertEqual(builder(declared_app).app, declared_app)
