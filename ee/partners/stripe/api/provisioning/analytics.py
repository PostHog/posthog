"""Product analytics for the Stripe provisioning namespace.

Provisioning events share one vocabulary across all provisioning API surfaces;
``path_namespace`` identifies which surface served the request, so per-surface
traffic is directly observable.
"""

from __future__ import annotations

import uuid

import posthoganalytics

from posthog.models.oauth import OAuthApplication

PATH_NAMESPACE = "partners_stripe"


def capture_provisioning_event(
    event_type: str,
    outcome: str,
    *,
    partner: OAuthApplication | None = None,
    **extra: object,
) -> None:
    team_id = extra.get("team_id")
    distinct_id = f"agentic_provisioning_team_{team_id}" if team_id else f"agentic_provisioning_{uuid.uuid4().hex[:16]}"
    properties: dict[str, object] = {
        "outcome": outcome,
        "path_namespace": PATH_NAMESPACE,
        # Single-caller namespace; tag the type without reading app config.
        "partner_type": "stripe",
        **extra,
    }
    if partner is not None:
        properties.setdefault("partner_id", str(partner.id))
        properties.setdefault("client_name", partner.name)
    posthoganalytics.capture(
        f"agentic_provisioning {event_type}",
        distinct_id=distinct_id,
        properties=properties,
    )


def capture_signature_event(outcome: str, status_code: int, endpoint: str, **extra: object) -> None:
    posthoganalytics.capture(
        "agentic_provisioning signature verification",
        distinct_id=f"agentic_provisioning_{uuid.uuid4().hex[:16]}",
        properties={
            "outcome": outcome,
            "status_code": status_code,
            "endpoint": endpoint,
            "path_namespace": PATH_NAMESPACE,
            **extra,
        },
    )


def capture_region_proxy_event(outcome: str, **props: object) -> None:
    posthoganalytics.capture(
        "agentic_provisioning region_proxy",
        distinct_id=f"agentic_provisioning_{uuid.uuid4().hex[:16]}",
        properties={"outcome": outcome, "path_namespace": PATH_NAMESPACE, **props},
    )
