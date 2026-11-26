"""Who can grant, see and pick each scope: the internal, hidden, privileged, grantable and resource sets."""

from . import catalog

# Internal: markers that PostHog's own code puts on tokens it mints for agents, sandboxes and
# scheduled runs. No person or OAuth client can grant or request one, because each unlocks
# something only PostHog itself should do. Every user-facing scope list leaves them out.
INTERNAL_API_SCOPE_OBJECTS: frozenset[catalog.APIScopeObject] = frozenset(
    {
        "clickhouse_test_cluster_perf",
        # Grants Context Wiki writes only to write-enabled sandbox runs. Kept
        # separate from internal_run because read-only runs carry that marker.
        "context_layer_internal",
        # Files a suggestion on a workflow, and nothing else. Programmatic-only so no personal key,
        # OAuth app or logged-in session can queue one: PostHog's own scout is the only producer, and
        # a person resolves suggestions rather than writing them.
        "hog_flow_proposal",
        # Narrows `internal_run`: the run behind this token was started by a person
        # pressing a button, not by one of PostHog's own schedulers. Both markers are
        # minted server-side, so neither can be self-granted; the LLM gateway meters
        # user-started runs against their own, much smaller budget because their volume
        # is chosen by the customer rather than by us.
        "interactive_run",
        # Provenance marker on tokens minted server-side for a sandbox/agent run
        # (never via the consent flow or a personal API key). The LLM gateway requires
        # it on the internal products that share the PostHog Desktop OAuth app so a user's
        # own credential can't reach them — see services/llm-gateway products/config.py.
        "internal_run",
        # Marks a sandbox OAuth token as belonging to a trusted built-in agent.
        # MCP Store uses it to deny the human/member control plane and force the
        # agent through its own explicit gateway grants.
        "mcp_builtin_agent",
        "scout_experiment_internal",
        # Sandbox-only writes for the headless Signals agent (memory create/delete,
        # finding emit). Read access for the same surface lives on the public
        # `signal_scout` object so user-grantable PAKs can still inspect runs/memory.
        "signal_scout_internal",
        "signal_scout_monitoring",
        # Sandbox-only write for the scout report channel (emit_report / edit_report).
        # Split out from `signal_scout_internal` so it can be granted ONLY to scouts that
        # opted into the report tools (via the `signals_scout_reports` posture) — every
        # other scout's token lacks it, so the MCP server strips those tools entirely.
        "signal_scout_report",
        # Sandbox-only write for the shared scratchpad (remember / forget). Split out from
        # `signal_scout_internal` for the same reason as the report channel: the report
        # pipeline's research and implementation runs need durable memory, and granting it
        # through the scout object would hand them `emit_signal` and `record_output` too.
        "signal_scratchpad_internal",
        # Marks tokens minted for Slack tasks so spend policy does not depend on the
        # caller-selected LLM gateway product route.
        "slack_run",
    }
)

# Hidden: staff-only or unreleased surfaces. A person can still type one into a personal API key,
# but no scope picker shows it and no OAuth discovery document lists it, so customers never come
# across it. The MCP server treats a tool that needs one as staff-only and hides it from everyone else.
OAUTH_HIDDEN_SCOPE_OBJECTS: frozenset[catalog.APIScopeObject] = frozenset(
    {
        "wizard_session",
        "wizard_run",
        "query_performance",
        # Staff-only managed-migrations (batch import) support diagnostics, also gated by
        # `is_staff`. Distinct from the public `batch_import` object on purpose: that one is
        # OAuth-advertised, and a customer-grantable scope must never name a staff surface.
        "batch_import_support",
        # Its only route accepts project secret API keys alone, so only that key picker offers it.
        "messaging_preference",
    }
)

# Every object except the internal ones: what a personal API key, an OAuth grant or an access
# control rule can name. The access control API types its resource fields with it, so the
# generated frontend enum comes from here.
GRANTABLE_API_SCOPE_OBJECTS: tuple[catalog.APIScopeObject, ...] = tuple(
    obj for obj in catalog.API_SCOPE_OBJECTS if obj not in INTERNAL_API_SCOPE_OBJECTS
)

# Grantable objects that no scope picker offers, each with the reason: umbrella resources, and
# retired scopes kept so that old clients that still request them keep working.
SCOPE_OBJECTS_OMITTED_FROM_PICKERS: dict[catalog.APIScopeObject, str] = {
    # Umbrella access-control resource that `warehouse_view`/`warehouse_table` inherit from.
    # The granular scopes are offered instead.
    "warehouse_objects": "Umbrella resource: grant warehouse_view/warehouse_table instead.",
    # Pending removal. No endpoint enforces these, so they do nothing when granted.
    # Remove them from `APIScopeObject` whenever you like: `/authorize` drops a requested scope that no
    # longer exists, and saving a personal API key drops one the key still holds.
    "batch_import": "Pending removal: no endpoint enforces it (its viewset is INTERNAL).",
    "mcp_registry": "Retired: no endpoint enforces it; kept for OAuth clients that still request it.",
    "external_data_schema": "Pending removal: covered by external_data_source; no viewset uses it.",
    "vision_action": "Retired: no endpoint enforces it; kept for desktop OAuth clients that still request it.",
    "link": "Retired: no endpoint enforces it; kept for desktop OAuth clients that still request it.",
    "live_debugger": "Retired: no endpoint enforces it; kept for desktop OAuth clients that still request it.",
    "loop": "Retired: no endpoint enforces it; kept for desktop OAuth clients that still request it.",
    "knowledge_writer": "Retired: its only endpoint was removed, so no endpoint enforces it.",
    # Access control resources that no token check reads, so granting them to a token does nothing.
    "toolbar": "Access control resource only: no endpoint checks it as a token scope.",
    "revenue_analytics": "Access control resource only: no endpoint checks it as a token scope.",
}

# What people see and choose in the scope pickers, the scope reference and `/oauth/scopes/`:
# every grantable object except the hidden and omitted ones. Each needs a `ScopeDoc`
# (see `posthog/scope_docs.py`).
EXPOSED_SCOPE_OBJECTS: tuple[catalog.APIScopeObject, ...] = tuple(
    obj
    for obj in GRANTABLE_API_SCOPE_OBJECTS
    if obj not in OAUTH_HIDDEN_SCOPE_OBJECTS and obj not in SCOPE_OBJECTS_OMITTED_FROM_PICKERS
)

# Naming convention: `*_SCOPE_OBJECTS` hold scope objects, and `*_SCOPES` hold `obj:action`
# strings. The string sets below are what `OAuthApplication.scopes` and the OAuth ceilings use.

# Every grantable `obj:action` string, that is every scope except the internal ones.
ALL_SCOPES: frozenset[str] = frozenset(
    f"{obj}:{action}" for obj in GRANTABLE_API_SCOPE_OBJECTS for action in catalog.API_SCOPE_ACTIONS
)

# Privileged: public scopes that an OAuth app must never grant itself, because they run paid LLM
# calls through the gateway (`llm_gateway`). Unlike hidden scopes, the key picker shows them,
# outside the presets. An OAuth app gets one only when staff put it on the app's ceiling (Django
# admin, the Stripe seed list or a data migration). Self-registration (DCR, CIMD) drops them.
PRIVILEGED_SCOPES: frozenset[str] = frozenset({"llm_gateway:read", "llm_gateway:write"})

# `OAUTH_HIDDEN_SCOPE_OBJECTS` as `obj:action` strings.
OAUTH_SCOPES_HIDDEN: frozenset[str] = (
    frozenset(f"{obj}:{action}" for obj in OAUTH_HIDDEN_SCOPE_OBJECTS for action in catalog.API_SCOPE_ACTIONS)
    & ALL_SCOPES
)

# Resource: the scopes any OAuth client may hold. This is the ceiling of an app with no `scopes`,
# and the most a self-registered app can declare. Identity scopes are separate
# (`ALWAYS_ALLOWED_SCOPES`).
UNPRIVILEGED_SCOPES: frozenset[str] = ALL_SCOPES - PRIVILEGED_SCOPES - OAUTH_SCOPES_HIDDEN

# What a risky scope lets a token do, shown wherever a person grants scopes to a token so they add it with care.
RISKY_SCOPE_WARNINGS: dict[str, str] = {
    "access_control:write": "Changes who can access resources in this project.",
    "approvals:write": "Approves or rejects change requests that gate other changes.",
    "autoresearch:write": "Starts agent runs that get their own longer-lived token.",
    "billing:read": "Reads the whole organization's billing details, not just this project's.",
    "billing:write": "Changes the organization's subscription and payment details.",
    "hog_flow:write": "Runs workflow code that can use the stored credentials of the project's integrations.",
    "hog_function:write": "Runs code, including on your website, that can use the stored credentials of the project's integrations.",
    "integration:write": "Connects and changes third-party integrations and their stored credentials.",
    "llm_provider_key:write": "Stores and changes LLM provider API keys.",
    "organization:write": "Changes organization settings, including roles and OAuth apps.",
    "organization_integration:write": "Connects and changes organization-wide integrations and their stored credentials.",
    "organization_member:write": "Invites and removes organization members and changes their roles, so it can give people access beyond this token's scopes.",
    "sharing_configuration:read": "Reads the access tokens of public sharing links, which keep working after this token expires.",
    "sharing_configuration:write": "Creates public sharing links that anyone with the link can open.",
    "user:read": "Reads the account details of the user the token acts as, including every organization and project they belong to.",
    "user:write": "Changes the account of the user the token acts as.",
}


def get_scope_descriptions() -> dict[str, str]:
    return {
        f"{obj}:{action}": f"{action.capitalize()} access to {obj}"
        for obj in catalog.API_SCOPE_OBJECTS
        if obj not in INTERNAL_API_SCOPE_OBJECTS
        for action in catalog.API_SCOPE_ACTIONS
    }
