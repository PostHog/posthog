"""Product analytics events for the agentic provisioning API."""

from __future__ import annotations

import uuid

import posthoganalytics

from posthog.models.oauth import OAuthApplication


def _anonymous_distinct_id() -> str:
    return f"agentic_provisioning_{uuid.uuid4().hex[:16]}"


def capture_provisioning_event(
    event_type: str,
    outcome: str,
    *,
    partner: OAuthApplication | None = None,
    **extra: object,
) -> None:
    team_id = extra.get("team_id")
    distinct_id = f"agentic_provisioning_team_{team_id}" if team_id else _anonymous_distinct_id()
    properties: dict[str, object] = {"outcome": outcome, **extra}
    if partner is not None:
        properties.setdefault("partner_id", str(partner.id))
        properties.setdefault("client_name", partner.name)
    posthoganalytics.capture(
        f"agentic_provisioning {event_type}",
        distinct_id=distinct_id,
        properties=properties,
    )


def capture_deep_link_event(outcome: str, **extra: object) -> None:
    capture_provisioning_event("deep link login", outcome, partner=None, **extra)


def capture_auth_event(app: OAuthApplication, outcome: str, **extra: object) -> None:
    posthoganalytics.capture(
        "agentic_provisioning auth",
        distinct_id=_anonymous_distinct_id(),
        properties={
            "outcome": outcome,
            "client_name": app.name,
            "client_type": app.client_type,
            "app_id": str(app.id),
            **extra,
        },
    )


def capture_region_proxy_event(outcome: str, **props: object) -> None:
    posthoganalytics.capture(
        "agentic_provisioning region_proxy",
        distinct_id=_anonymous_distinct_id(),
        properties={"outcome": outcome, **props},
    )
