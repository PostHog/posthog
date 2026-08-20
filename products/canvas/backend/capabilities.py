"""Comparison of canvas capability manifests.

A canvas's declared capabilities (`project.capabilities`) are its permission
boundary: which insights it may read, which events it may capture, whether it
may run inline queries, and which network origins it may reach. Widening that
boundary is the security-relevant direction, so it gets a first-class,
structured answer rather than a raw manifest diff.
"""

from dataclasses import dataclass


def _posthog_section(manifest: dict | None) -> dict:
    return (manifest or {}).get("posthog") or {}


def _network_origins(manifest: dict | None) -> list[str]:
    return ((manifest or {}).get("network") or {}).get("origins") or []


def declared_state_scopes(manifest: dict | None) -> set[str]:
    """The ph.state scopes a capabilities manifest declares."""
    return set(_posthog_section(manifest).get("state") or [])


def declared_actions(manifest: dict | None) -> set[str]:
    """The ph.actions verbs a capabilities manifest declares."""
    return set(_posthog_section(manifest).get("actions") or [])


@dataclass(frozen=True, kw_only=True)
class CapabilityWidening:
    """What `after` declares beyond `before`. Narrowings are not reported here
    because this type carries the pre-publish "this grants more access" signal;
    the activity log records the full diff for history."""

    insights_added: list[str]
    capture_events_added: list[str]
    inline_queries_enabled: bool
    agent_requests_enabled: bool
    network_origins_added: list[str]
    state_scopes_added: list[str]
    actions_added: list[str]

    @property
    def widens(self) -> bool:
        return bool(
            self.insights_added
            or self.capture_events_added
            or self.inline_queries_enabled
            or self.agent_requests_enabled
            or self.network_origins_added
            or self.state_scopes_added
            or self.actions_added
        )


def capability_widening(before: dict | None, after: dict | None) -> CapabilityWidening:
    """How `after`'s declared capabilities grow `before`'s.

    A `before` of None (a baseline that predates the capabilities snapshot)
    is treated as empty, so everything `after` declares reports as an
    addition, because over-flagging is the safe direction for an advisory signal.
    """
    before_ph = _posthog_section(before)
    after_ph = _posthog_section(after)
    return CapabilityWidening(
        insights_added=sorted(set(after_ph.get("insights") or []) - set(before_ph.get("insights") or [])),
        capture_events_added=sorted(
            set(after_ph.get("captureEvents") or []) - set(before_ph.get("captureEvents") or [])
        ),
        inline_queries_enabled=bool(after_ph.get("inlineQueries")) and not bool(before_ph.get("inlineQueries")),
        agent_requests_enabled=bool(after_ph.get("agentRequests")) and not bool(before_ph.get("agentRequests")),
        network_origins_added=sorted(set(_network_origins(after)) - set(_network_origins(before))),
        state_scopes_added=sorted(set(after_ph.get("state") or []) - set(before_ph.get("state") or [])),
        actions_added=sorted(set(after_ph.get("actions") or []) - set(before_ph.get("actions") or [])),
    )
