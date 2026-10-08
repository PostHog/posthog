from collections.abc import Callable

from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.ingress.github.provider import build_github_provider
from posthog.ingress.mailgun.provider import build_mailgun_provider
from posthog.ingress.providers import UnknownApp, WebhookProvider
from posthog.ingress.slack.provider import build_slack_interactivity_provider, build_slack_provider
from posthog.ingress.sns.provider import build_sns_provider
from posthog.ingress.views import build_webhook_view


def _github(app: str) -> WebhookProvider:
    return build_github_provider(app)


def _mailgun(app: str) -> WebhookProvider:
    return build_mailgun_provider(app, signing_key_getter=lambda: "signing-key")


def _slack(app: str) -> WebhookProvider:
    return build_slack_provider(secret_getter=lambda: "signing-secret", app=app)


def _sns(app: str) -> WebhookProvider:
    return build_sns_provider(topic_arns_setting="WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS", app=app)


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


def _no_secret() -> str | None:
    return None


def _json_post() -> HttpRequest:
    return RequestFactory().post("/webhook/", data="{}", content_type="application/json")


def _form_post() -> HttpRequest:
    # Mailgun and Slack interactivity read a form, and Mailgun refuses any other content type
    # before it looks at the secret at all.
    return RequestFactory().post("/webhook/", data={"timestamp": "1", "token": "t", "signature": "s"})


def _unconfigured_mailgun(app: str) -> WebhookProvider:
    return build_mailgun_provider(app, signing_key_getter=_no_secret)


# One row per endpoint that answered 403 for a missing secret before it moved into this package.
UNCONFIGURED_ENDPOINTS = [
    ("slack_events", lambda: build_slack_provider(secret_getter=_no_secret), _json_post),
    ("slack_interactivity", lambda: build_slack_interactivity_provider(secret_getter=_no_secret), _form_post),
    ("mailgun_inbound", lambda: _unconfigured_mailgun("inbound"), _form_post),
    ("mailgun_outbound", lambda: _unconfigured_mailgun("outbound"), _form_post),
    ("mailgun_capture", lambda: _unconfigured_mailgun("capture"), _form_post),
]


class TestUnconfiguredEndpoints(SimpleTestCase):
    @parameterized.expand(UNCONFIGURED_ENDPOINTS)
    def test_a_missing_secret_still_answers_403_with_no_reason(
        self,
        _name: str,
        build_provider: Callable[[], WebhookProvider],
        build_request: Callable[[], HttpRequest],
    ) -> None:
        response = build_webhook_view(build_provider())(build_request())

        # The package default is 500, which would turn every anonymous probe of these public URLs
        # into a server error on any instance that never set the secret.
        self.assertEqual(response.status_code, 403)
        # And the body must not tell that caller which of the two it was.
        self.assertEqual(response.content, b"")
