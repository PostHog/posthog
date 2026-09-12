"""Comparison of canvas capability manifests.

A canvas's declared capabilities (`project.capabilities`) are its permission
boundary: which insights it may read, which events it may capture, whether it
may run inline queries, and which network origins it may reach. Widening that
boundary is the security-relevant direction, so it gets a first-class,
structured answer rather than a raw manifest diff.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, kw_only=True)
class ConnectorGrant:
    """One provider a manifest lets the canvas call, with the tools it may use."""

    provider: str
    tools: list[str]


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


def declared_connectors(manifest: dict | None) -> dict[str, set[str]]:
    """The ph.connectors tools a capabilities manifest declares, keyed by provider."""
    declared: dict[str, set[str]] = {}
    for entry in (manifest or {}).get("connectors") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("provider"), str):
            continue
        declared.setdefault(entry["provider"], set()).update(
            tool for tool in entry.get("tools") or [] if isinstance(tool, str)
        )
    return declared


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
    connectors_added: list[ConnectorGrant]

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
            or self.connectors_added
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
        connectors_added=_connectors_added(declared_connectors(before), declared_connectors(after)),
    )


def _connectors_added(before: dict[str, set[str]], after: dict[str, set[str]]) -> list[ConnectorGrant]:
    added = []
    for provider in sorted(after):
        tools = sorted(after[provider] - before.get(provider, set()))
        if tools:
            added.append(ConnectorGrant(provider=provider, tools=tools))
    return added


# What each access grant looks like when it grants nothing. `network.origins` becomes the
# artifact's CSP, and the rest gate the host bridge. Everything else a manifest carries (notebook
# frames, for example) describes the canvas rather than what it may reach, so it survives.
_UNGRANTED_POSTHOG_FIELDS: dict[str, Any] = {
    "insights": [],
    "captureEvents": [],
    "inlineQueries": False,
    "agentRequests": False,
    "state": [],
    "actions": [],
}


def without_granted_capabilities(manifest: dict | None) -> dict:
    """The manifest with every access grant emptied, keeping its shape and the rest of its fields.

    A copy of someone else's canvas must not inherit their permission boundary: the grants were
    reviewed against the source's project, not the one the copy lands in. The copy starts with no
    network egress, no connectors and no PostHog access, and its owner re-declares what it needs
    through a publish, where `capability_widening` surfaces the grant before it ships.
    """
    stripped = dict(manifest or {})
    posthog = _posthog_section(manifest)
    if posthog:
        stripped["posthog"] = {key: _UNGRANTED_POSTHOG_FIELDS.get(key, value) for key, value in posthog.items()}
    if isinstance(stripped.get("network"), dict):
        stripped["network"] = {**stripped["network"], "origins": []}
    if "connectors" in stripped:
        stripped["connectors"] = []
    return stripped
