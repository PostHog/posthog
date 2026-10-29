"""GitHub App deliveries, for every App PostHog runs.

Two apps share this incarnation: the customer-facing PostHog App (`posthog`, secret in
instance settings so an operator can rotate it without a deploy) and the Stamphog review App
(`stamphog`, secret in env because it is instance-wide infrastructure). Both secrets are read from
the credentials service first, and from those settings while the service does not hold them.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from posthog.cache_utils import cache_for
from posthog.credentials_service.callers import CredentialsCaller
from posthog.credentials_service.instance_settings import get_or_instance_setting
from posthog.credentials_service.settings_fallback import get_or_settings
from posthog.ingress.contracts import ProviderSpec, WebhookConsumer, WebhookDelivery
from posthog.ingress.providers import WebhookProvider, require_known_app
from posthog.ingress.verify.schemes import HmacSha256, SignatureScheme

# What each App is subscribed to. A consumer for an event type outside its App's set fails
# registry validation, which is the point: it would never run. The two Apps are subscribed
# separately in GitHub, so they get separate sets rather than one shared superset.
GITHUB_EVENT_TYPES = frozenset(
    {
        "issues",
        "issue_comment",
        "pull_request",
        "pull_request_review",
        "installation",
        "installation_repositories",
        "push",
    }
)

# The Stamphog App reviews pull requests and keeps its repo-config rows in step with GitHub.
STAMPHOG_EVENT_TYPES = frozenset({"pull_request", "installation", "installation_repositories"})


# Every delivery is verified, so each secret is read under a cache and not once per request. A
# rotation reaches each process within five minutes.
@cache_for(timedelta(minutes=5))
def _posthog_app_secret() -> str | None:
    return get_or_instance_setting("GITHUB_WEBHOOK_SECRET", CredentialsCaller.INTEGRATIONS) or None


@cache_for(timedelta(minutes=5))
def _stamphog_app_secret() -> str | None:
    return get_or_settings("STAMPHOG_GITHUB_APP_WEBHOOK_SECRET", CredentialsCaller.STAMPHOG) or None


_SECRET_GETTERS: Mapping[str, Callable[[], str | None]] = {
    "posthog": _posthog_app_secret,
    "stamphog": _stamphog_app_secret,
}

_APP_EVENT_TYPES: Mapping[str, frozenset[str]] = {
    "posthog": GITHUB_EVENT_TYPES,
    "stamphog": STAMPHOG_EVENT_TYPES,
}

SPECS = tuple(
    ProviderSpec(provider="github", app=app, event_types=_APP_EVENT_TYPES[app]) for app in sorted(_SECRET_GETTERS)
)


def _installation_context(payload: Mapping[str, Any]) -> dict[str, str]:
    installation = payload.get("installation")
    if not isinstance(installation, Mapping):
        return {}
    installation_id = installation.get("id")
    return {"installation_id": str(installation_id)} if installation_id is not None else {}


class GitHubProvider(WebhookProvider):
    provider = "github"

    def __init__(self, app: str) -> None:
        require_known_app(self.provider, app, SPECS)
        self.app = app
        self._scheme = HmacSha256(
            secret_getter=_SECRET_GETTERS[app],
            signature_header="X-Hub-Signature-256",
            prefix="sha256=",
        )

    def scheme(self) -> SignatureScheme:
        return self._scheme

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        if not isinstance(payload, Mapping):
            return ()
        return (
            WebhookDelivery(
                provider=self.provider,
                app=self.app,
                delivery_id=request.headers.get("X-GitHub-Delivery") or None,
                event_type=request.headers.get("X-GitHub-Event", ""),
                payload=payload,
                received_at=timezone.now(),
                context=_installation_context(payload),
            ),
        )


def build_github_provider(app: str) -> GitHubProvider:
    return GitHubProvider(app)


def _run_installation_lifecycle(delivery: WebhookDelivery) -> None:
    from posthog.api.github_callback.installation_events import (
        handle_installation_event,  # noqa: PLC0415 - keeps the integration models off the incarnation's import path
    )

    handle_installation_event(dict(delivery.payload))


def _run_installation_repositories(delivery: WebhookDelivery) -> None:
    from posthog.api.github_callback.installation_events import (
        handle_installation_repositories_event,  # noqa: PLC0415 - keeps the integration models off the incarnation's import path
    )

    handle_installation_repositories_event(dict(delivery.payload))


# Core owns the installation lifecycle: it is what keeps PostHog's own integration rows in
# step with GitHub, so no product registers it.
CORE_CONSUMERS = (
    WebhookConsumer(
        name="installation_lifecycle",
        provider="github",
        app="posthog",
        event_types=frozenset({"installation"}),
        handler=_run_installation_lifecycle,
    ),
    WebhookConsumer(
        name="installation_repositories",
        provider="github",
        app="posthog",
        event_types=frozenset({"installation_repositories"}),
        handler=_run_installation_repositories,
    ),
)
