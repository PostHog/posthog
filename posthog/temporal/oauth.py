from datetime import timedelta
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_oauth_access_token
from posthog.scopes import (
    API_SCOPE_OBJECTS,
    INTERNAL_API_SCOPE_OBJECTS,
    MCP_BUILT_IN_AGENT_SCOPE,
    OAUTH_HIDDEN_SCOPE_OBJECTS,
    resolve_ceiling,
)
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

ARRAY_APP_CLIENT_ID_US = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W"
ARRAY_APP_CLIENT_ID_EU = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9"
ARRAY_APP_CLIENT_ID_DEV = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"
POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_US = "a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm"
POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_EU = "1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU"
POSTHOG_AI_APP_CLIENT_ID_US = "N6UgOECSl98ag1xajxPphGApQXYEVvJIwzCXotKu"
POSTHOG_AI_APP_CLIENT_ID_EU = "0Lizwa3mFSlBuEEQ8V8FMJlskUXpDuSmoEdhzxyi"
POSTHOG_AI_APP_CLIENT_ID_DEV = "DD2ZLG6a2YEUtpPANSzSiIBPuUryYmbndLnKKUy1"
SIGNALS_APP_CLIENT_ID_US = "jpSRPhGBBbDGpKprit9bgJEuo6oUTa8ULymqf8PE"
SIGNALS_APP_CLIENT_ID_EU = "nqZsiFEbu1fCWDK3r8QtSGwKmmANxVIgfZmTXywk"
SIGNALS_APP_CLIENT_ID_DEV = "xMT3Nejjbi4lUdhJLkzmCVJKFsx0JsHXdU0pIjl8"

# The LLM gateway authorizes by application id, so these must stay equal to
# POSTHOG_CODE_DEV_APP_ID / POSTHOG_AI_DEV_APP_ID / SIGNALS_DEV_APP_ID in
# llm_gateway/products/config.py.
ARRAY_APP_ID_DEV = "019ebb47-c750-0000-e1ea-723a6ff112d3"
POSTHOG_AI_APP_ID_DEV = "019edb1a-cce4-0000-1f6d-682061862da9"
SIGNALS_APP_ID_DEV = "019fb2ee-9d54-0000-61d9-faf825230d44"

POSTHOG_DESKTOP_OAUTH_CLIENT_IDS = frozenset(
    {
        ARRAY_APP_CLIENT_ID_US,
        ARRAY_APP_CLIENT_ID_EU,
        ARRAY_APP_CLIENT_ID_DEV,
        POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_US,
        POSTHOG_DESKTOP_MOBILE_APP_CLIENT_ID_EU,
    }
)

# OAuth applications used to mint sandbox agent tokens. The Array applications also
# issue interactive Desktop grants, so membership in this set does not prove sandbox origin.
POSTHOG_CODE_OAUTH_APP_CLIENT_IDS = frozenset({ARRAY_APP_CLIENT_ID_US, ARRAY_APP_CLIENT_ID_EU, ARRAY_APP_CLIENT_ID_DEV})

# The dedicated "Signals" OAuth app, minted for every Signals sandbox run (scouts and
# report-driven tasks alike). Held apart from the Array app so the LLM gateway can pin the
# `signals` product to it: while the two share an app, a Signals token also satisfies every
# other product that app is authorized for, and the product a caller declares is a path
# segment it chooses, so a per-product budget on a shared app is advisory rather than binding.
SIGNALS_OAUTH_APP_CLIENT_IDS = frozenset(
    {
        SIGNALS_APP_CLIENT_ID_US,
        SIGNALS_APP_CLIENT_ID_EU,
        SIGNALS_APP_CLIENT_ID_DEV,
    }
)

# Apps that mint tokens for a cloud task's own coding agent, which is what the task-comment
# channel is restricted to. Signals joined when its runs moved off the Array app; PostHog AI is
# deliberately absent, as it was before. The `sandbox_task_id` binding on the token is what
# actually scopes access to one task — this set only keeps unrelated first-party tokens out.
TASK_AGENT_OAUTH_APP_CLIENT_IDS = frozenset(
    {
        *POSTHOG_CODE_OAUTH_APP_CLIENT_IDS,
        *SIGNALS_OAUTH_APP_CLIENT_IDS,
    }
)

SANDBOX_OAUTH_APP_CLIENT_IDS = frozenset(
    {
        *POSTHOG_CODE_OAUTH_APP_CLIENT_IDS,
        POSTHOG_AI_APP_CLIENT_ID_US,
        POSTHOG_AI_APP_CLIENT_ID_EU,
        POSTHOG_AI_APP_CLIENT_ID_DEV,
        *SIGNALS_OAUTH_APP_CLIENT_IDS,
    }
)

# The dedicated "PostHog AI" OAuth app. Tokens minted against it are only ever created
# server-side for PostHog AI sandbox agents, so a request bearing one is authoritatively
# attributable to PostHog AI regardless of spoofable user-agent or client headers.
POSTHOG_AI_OAUTH_APP_CLIENT_IDS = frozenset(
    {
        POSTHOG_AI_APP_CLIENT_ID_US,
        POSTHOG_AI_APP_CLIENT_ID_EU,
        POSTHOG_AI_APP_CLIENT_ID_DEV,
    }
)

McpScopePreset = Literal["read_only", "full", "signals_scout", "signals_scout_reports"]
SandboxOAuthApplication = Literal["array", "posthog_ai", "signals"]

# Granted only to sandbox runs a person started by hand (see `interactive_run` in
# posthog/scopes.py). Kept out of `INTERNAL_SCOPES` so a scheduled run never carries it.
INTERACTIVE_RUN_SCOPE = "interactive_run:read"


INTERNAL_SCOPES: list[str] = [
    "task:write",
    "llm_gateway:read",
    # Provenance marker: proves a token was minted here (server-side), not obtained by a
    # user via the consent flow or a personal API key. `internal_run` is an internal scope,
    # so it's rejected by every user-facing scope validator and can't be forged. The LLM
    # gateway requires it on the internal products that share the PostHog Desktop OAuth app
    # (background_agents, signals, slack_app, conversations) so a user's own OAuth token
    # can't route around the posthog_code free-tier model gate through those.
    "internal_run:read",
]

# Writes for the Signals scout harness — sandbox-only because the scope object is in
# `INTERNAL_API_SCOPE_OBJECTS` and so cannot be minted via the personal API key UI or
# granted through the OAuth consent flow. Reads use the public `signal_scout:read` scope.
# Kept OUT of the global `INTERNAL_SCOPES` so it is added ONLY for the `signals_scout`
# preset — unrelated `full`/`read_only` task tokens must never carry scout write access.
SCOUT_INTERNAL_SCOPES: list[str] = [
    "signal_scout_internal:write",
]


# The scout report channel (emit_report / edit_report). Held separate from
# `SCOUT_INTERNAL_SCOPES` and added ONLY for the `signals_scout_reports` posture, so a scout
# carries it only when its skill opted into the report tools via `allowed_tools`. A baseline
# scout's token never carries this scope, so the MCP server strips the report tools from its
# toolset entirely — they can't bleed into a run that didn't opt in.
SCOUT_REPORT_SCOPES: list[str] = [
    "signal_scout_report:write",
]

LOOP_CONTEXT_INTERNAL_SCOPE = "loop_context_internal:write"


# A deliberately narrow set of user-facing WRITE scopes granted to the Signals scout
# sandbox so scouts can produce durable artifacts as part of a finding — e.g. a notebook
# that documents and illustrates an emitted anomaly. Unlike `SCOUT_INTERNAL_SCOPES` these
# are ordinary public scopes (also present in the `full` preset), but they are added to the
# scout posture ONLY on the `signals_scout` branch below, never via the global
# `INTERNAL_SCOPES`, so `read_only` task tokens stay strictly read-only. Keep this list
# small: every entry is real write access an autonomous scout can exercise unattended, so
# add a scope here only when a scout genuinely needs to create that kind of artifact.
# NOTE: scopes here are object-level, not tool-level. `notebook:write` also exposes the
# `notebooks-destroy` / `notebooks-partial-update` MCP tools, not just `notebooks-create`,
# so in principle a scout (or a prompt-injected run) could modify or soft-delete existing
# notebooks in its own project. Accepted as low-risk for now — the token is scoped to a
# single team, destroy is a recoverable soft-delete, and emits are rare — and monitored in
# practice; tool-level (create-only) restriction isn't cheap in the current sandbox wiring.
SCOUT_USER_WRITE_SCOPES: list[str] = [
    "notebook:write",
]


# Derived from posthog.scopes so the token issued to a sandboxed agent cannot
# drift out of subset of what the MCP server advertises in
# `services/mcp/src/lib/oauth-scopes.generated.ts` (itself generated from
# `get_oauth_scopes_supported()` via `bin/build-mcp-oauth-scopes.py`). Scopes
# already covered by INTERNAL_SCOPES are excluded so resolve_scopes() doesn't
# emit duplicates.
def _build_mcp_scopes(action: Literal["read", "write"]) -> list[str]:
    excluded_objects = INTERNAL_API_SCOPE_OBJECTS | OAUTH_HIDDEN_SCOPE_OBJECTS
    internal_set = set(INTERNAL_SCOPES)
    return [
        f"{obj}:{action}"
        for obj in API_SCOPE_OBJECTS
        if obj not in excluded_objects and f"{obj}:{action}" not in internal_set
    ]


MCP_READ_SCOPES: list[str] = _build_mcp_scopes("read")
MCP_WRITE_SCOPES: list[str] = _build_mcp_scopes("write")

TOKEN_EXPIRATION_SECONDS = 60 * 60 * 6  # 6 hours

PosthogMcpScopes = McpScopePreset | list[str]

MCP_SCOPE_PRESETS = ("read_only", "full", "signals_scout", "signals_scout_reports")


def resolve_scopes(
    scopes: PosthogMcpScopes = "read_only",
    *,
    include_internal_scopes: bool = True,
) -> list[str]:
    internal = list(INTERNAL_SCOPES) if include_internal_scopes else []
    if isinstance(scopes, str):
        if scopes == "full":
            resolved = [*MCP_READ_SCOPES, *MCP_WRITE_SCOPES, *internal]
        elif scopes in ("signals_scout", "signals_scout_reports"):
            # The scout sandbox: reads, the scout's own internal write scope, and a narrow
            # allowlist of user-facing writes (`SCOUT_USER_WRITE_SCOPES`) for the durable
            # artifacts a finding can produce (e.g. a notebook). Both extra sets are added
            # ONLY here (not via the global `INTERNAL_SCOPES`), so unrelated `full`/`read_only`
            # task tokens never carry them. `has_write_scopes(...)` also reports True so the MCP
            # server doesn't enable read-only mode, which would otherwise strip the agent's own
            # internal-write tools (`signal_scout_internal:write` is annotated as not-read-only).
            #
            # `signals_scout_reports` is the same posture plus the report-channel scope, granted
            # only to a scout whose skill opted into emit_report/edit_report. A baseline scout
            # gets `signals_scout` (no report scope), so the MCP server strips the report tools.
            scout_internal = list(SCOUT_INTERNAL_SCOPES) if include_internal_scopes else []
            scout_report = (
                list(SCOUT_REPORT_SCOPES) if (scopes == "signals_scout_reports" and include_internal_scopes) else []
            )
            resolved = [*MCP_READ_SCOPES, *internal, *scout_internal, *scout_report, *SCOUT_USER_WRITE_SCOPES]
        else:
            # "read_only": reads + shared internal scopes only — no scout write scope.
            resolved = [*MCP_READ_SCOPES, *internal]
    else:
        resolved = [*scopes, *internal]
    return list(dict.fromkeys(resolved))


def has_write_scopes(scopes: PosthogMcpScopes) -> bool:
    if isinstance(scopes, str):
        # `signals_scout` reports True so the MCP server doesn't enable read-only mode for the
        # scout sandbox — the agent IS allowed to call the write tools its preset exists for
        # (remember/forget/emit_finding + the narrow `SCOUT_USER_WRITE_SCOPES`). Read-only mode
        # is a tool-annotation filter, not a scope filter, and would strip those tools
        # categorically without this opt-out.
        return scopes in ("full", "signals_scout", "signals_scout_reports")
    return any(s in MCP_WRITE_SCOPES for s in scopes)


def _get_client_id_for_region(*, region: str | None, us: str, eu: str, dev: str) -> str:
    if region == "EU":
        return eu
    if region == "US":
        return us
    return dev


def _get_oauth_app_for_client_id(client_id: str, app_name: str, region: str | None) -> OAuthApplication:
    if not client_id:
        raise RuntimeError(f"{app_name} app not configured for region {region}")

    try:
        return OAuthApplication.objects.get(client_id=client_id)
    except OAuthApplication.DoesNotExist as err:
        raise RuntimeError(f"{app_name} app not found for region {region} (client_id={client_id})") from err


def get_array_app() -> OAuthApplication:
    region = get_instance_region()
    client_id = _get_client_id_for_region(
        region=region,
        us=ARRAY_APP_CLIENT_ID_US,
        eu=ARRAY_APP_CLIENT_ID_EU,
        dev=ARRAY_APP_CLIENT_ID_DEV,
    )

    return _get_oauth_app_for_client_id(client_id, "Array", region)


def get_posthog_ai_app() -> OAuthApplication:
    region = get_instance_region()
    client_id = _get_client_id_for_region(
        region=region,
        us=POSTHOG_AI_APP_CLIENT_ID_US,
        eu=POSTHOG_AI_APP_CLIENT_ID_EU,
        dev=POSTHOG_AI_APP_CLIENT_ID_DEV,
    )

    return _get_oauth_app_for_client_id(client_id, "PostHog AI", region)


def get_signals_app() -> OAuthApplication | None:
    """The Signals sandbox app for this region, or None when it isn't provisioned here.

    Unlike the Array and PostHog AI resolvers this one never raises: the application rows are
    created per region out of band, so callers fall back to the Array app until the row exists
    rather than failing every Signals run in a region that hasn't been provisioned yet.
    """
    region = get_instance_region()
    client_id = _get_client_id_for_region(
        region=region,
        us=SIGNALS_APP_CLIENT_ID_US,
        eu=SIGNALS_APP_CLIENT_ID_EU,
        dev=SIGNALS_APP_CLIENT_ID_DEV,
    )
    if not client_id:
        return None
    return OAuthApplication.objects.filter(client_id=client_id).first()


def get_sandbox_oauth_app(application: SandboxOAuthApplication = "array") -> OAuthApplication:
    if application == "posthog_ai":
        return get_posthog_ai_app()
    if application == "signals":
        signals_app = get_signals_app()
        if signals_app is not None:
            return signals_app
        # The gateway no longer accepts Array tokens for the `signals` product, so this run's
        # inference calls will be rejected there. Minting still succeeds so the failure surfaces
        # in the run (with this log to explain it) rather than as an opaque kickoff error; the
        # real fix is provisioning the region's Signals application row.
        logger.warning("signals_oauth_app_missing_falling_back_to_array", region=get_instance_region())
    return get_array_app()


def _mint_oauth_access_token(
    user, team_id: int, *, app: OAuthApplication, scopes: list[str], sandbox_task_id: UUID | None = None
) -> str:
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        user=user,
        application=app,
        token=token_value,
        expires=timezone.now() + timedelta(seconds=TOKEN_EXPIRATION_SECONDS),
        scope=" ".join(dict.fromkeys(scopes)),
        scoped_teams=[team_id],
        sandbox_task_id=sandbox_task_id,
    )

    return token_value


def create_oauth_access_token_for_user(
    user,
    team_id: int,
    *,
    scopes: PosthogMcpScopes = "read_only",
    include_internal_scopes: bool = True,
    include_mcp_builtin_agent_scope: bool = False,
    include_interactive_run_scope: bool = False,
    application: SandboxOAuthApplication = "array",
    sandbox_task_id: UUID | None = None,
) -> str:
    resolved = resolve_scopes(scopes, include_internal_scopes=include_internal_scopes)
    if include_mcp_builtin_agent_scope:
        # Provenance marker: the MCP Store uses it to deny the human/member
        # surface and route the agent through its explicit gateway grants. It
        # does not narrow the token's other scopes.
        resolved.append(MCP_BUILT_IN_AGENT_SCOPE)
    if include_interactive_run_scope:
        # Provenance marker only — it grants no access. The LLM gateway meters a run
        # carrying it against the interactive budget instead of the pipeline's.
        resolved.append(INTERACTIVE_RUN_SCOPE)
    app = get_sandbox_oauth_app(application)
    return _mint_oauth_access_token(user, team_id, app=app, scopes=list(resolved), sandbox_task_id=sandbox_task_id)


def get_wizard_app() -> OAuthApplication:
    return _get_oauth_app_for_client_id(
        settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID, "PostHog Wizard", get_instance_region()
    )


def create_wizard_oauth_access_token_for_user(user, team_id: int) -> str:
    """Mint an OAuth access token under the wizard's own app for a cloud wizard run.

    Deliberately separate from the sandbox/agent token (`create_oauth_access_token_for_user`) so the
    wizard's scopes stay independent of the agent's. Uses the wizard app's configured scope ceiling.
    """
    app = get_wizard_app()

    ceiling = resolve_ceiling(app.ceiling_scopes)
    if ceiling is None or len(ceiling) == 0:
        raise RuntimeError("Wizard app has no scope ceiling. Must be configured in the database.")

    return _mint_oauth_access_token(user, team_id, app=app, scopes=sorted(ceiling))
