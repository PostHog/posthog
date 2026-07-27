from django.core.exceptions import ImproperlyConfigured

from posthog.settings.base_variables import DEBUG
from posthog.settings.utils import get_from_env, get_list

# Agent janitor service — Django proxies session list/detail/cancel requests here.
AGENT_JANITOR_BASE_URL = get_from_env("AGENT_JANITOR_BASE_URL", "http://localhost:3031")

# How agent-ingress addresses agents externally; must match the ingress's own
# ROUTING_MODE. "domain": slug in the host (<slug><suffix>); "path": slug in the
# path (<base>/agents/<slug>/...), used in local dev via bin/agent-tunnel.
AGENT_INGRESS_ROUTING_MODE = get_from_env("AGENT_INGRESS_ROUTING_MODE", "path")
if AGENT_INGRESS_ROUTING_MODE not in ("domain", "path"):
    raise ImproperlyConfigured(
        f"AGENT_INGRESS_ROUTING_MODE must be 'domain' or 'path', got '{AGENT_INGRESS_ROUTING_MODE}'"
    )

# Domain suffix for "domain" mode (e.g. .agents.us.posthog.com); empty → agent
# URLs are omitted (not externally reachable).
AGENT_INGRESS_DOMAIN_SUFFIX = get_from_env("AGENT_INGRESS_DOMAIN_SUFFIX", "")

# Public base URL for agent-ingress in "path" mode (Slack callbacks, webhooks);
# empty → the slack_events_url field is omitted from API responses. In local dev
# (DEBUG=True) we default to the local agent-ingress port so URLs surface
# without requiring a tunnel; production must set this explicitly.
AGENT_INGRESS_PUBLIC_URL = get_from_env("AGENT_INGRESS_PUBLIC_URL", "http://localhost:3030" if DEBUG else "")

# Shared HMAC key for trusted-service JWTs across the agent platform. Empty
# default fails safe: the janitor client skips the mint and the receiver 401s,
# surfacing the misconfig instead of signing with a baked-in dev string.
AGENT_INTERNAL_SIGNING_KEY = get_from_env("AGENT_INTERNAL_SIGNING_KEY", "")

# Teams allowed to set an agent's slug explicitly on create. Everyone else gets
# a server-minted globally-unique slug (the slug is a single global namespace —
# see AgentApplication). This is our escape hatch so first-party agents (e.g.
# the concierge) keep a stable, human-readable slug across environments.
# Comma-separated team ids. In local dev (DEBUG) the default project (1) is
# allowlisted so the example seeder is idempotent and agents get stable,
# human-readable slugs (e.g. `posthog-ai`) for Slack routing; prod sets it
# explicitly (empty → no team may set an explicit slug).
AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS: set[int] = {
    int(team_id) for team_id in get_list(get_from_env("AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS", "1" if DEBUG else ""))
}
