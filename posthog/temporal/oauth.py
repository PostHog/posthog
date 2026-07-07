from datetime import timedelta
from typing import Literal

from django.conf import settings
from django.utils import timezone

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_oauth_access_token
from posthog.scopes import API_SCOPE_OBJECTS, INTERNAL_API_SCOPE_OBJECTS, OAUTH_HIDDEN_SCOPE_OBJECTS, resolve_ceiling
from posthog.utils import get_instance_region

ARRAY_APP_CLIENT_ID_US = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W"
ARRAY_APP_CLIENT_ID_EU = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9"
ARRAY_APP_CLIENT_ID_DEV = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"
POSTHOG_AI_APP_CLIENT_ID_US = "N6UgOECSl98ag1xajxPphGApQXYEVvJIwzCXotKu"
POSTHOG_AI_APP_CLIENT_ID_EU = "0Lizwa3mFSlBuEEQ8V8FMJlskUXpDuSmoEdhzxyi"
POSTHOG_AI_APP_CLIENT_ID_DEV = "DD2ZLG6a2YEUtpPANSzSiIBPuUryYmbndLnKKUy1"

McpScopePreset = Literal["read_only", "full", "signals_scout", "signals_scout_reports"]
SandboxOAuthApplication = Literal["array", "posthog_ai"]


INTERNAL_SCOPES: list[str] = [
    "task:write",
    "llm_gateway:read",
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


def resolve_scopes(scopes: PosthogMcpScopes = "read_only", *, include_internal_scopes: bool = True) -> list[str]:
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


# Region values that legitimately use the dev/local OAuth apps. Anything else on a real
# deployment (a missing region, an unexpected value) is a misconfiguration — see
# `_get_client_id_for_region`.
_DEV_REGIONS = frozenset({"DEV", "LOCAL", "E2E"})


def _get_client_id_for_region(*, region: str | None, us: str, eu: str, dev: str) -> str:
    if region == "EU":
        return eu
    if region == "US":
        return us
    # The dev/local OAuth apps only exist in dev, local, and test environments. Silently
    # falling back to them elsewhere selects an app that isn't seeded in prod, so the lookup
    # later fails with a confusing `OAuthApplication.DoesNotExist` pointing at a dev client id.
    # Fail loudly here instead: an unresolved region on a real deployment almost always means
    # CLOUD_DEPLOYMENT isn't set on this worker.
    if region in _DEV_REGIONS or settings.DEBUG or settings.TEST:
        return dev
    raise RuntimeError(
        f"Cannot resolve OAuth client id for region {region!r}: refusing to fall back to the dev "
        "app outside a dev/local/test environment. Is CLOUD_DEPLOYMENT set on this worker?"
    )


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


def get_sandbox_oauth_app(application: SandboxOAuthApplication = "array") -> OAuthApplication:
    if application == "posthog_ai":
        return get_posthog_ai_app()
    return get_array_app()


def _mint_oauth_access_token(user, team_id: int, *, app: OAuthApplication, scopes: list[str]) -> str:
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        user=user,
        application=app,
        token=token_value,
        expires=timezone.now() + timedelta(seconds=TOKEN_EXPIRATION_SECONDS),
        scope=" ".join(dict.fromkeys(scopes)),
        scoped_teams=[team_id],
    )

    return token_value


def create_oauth_access_token_for_user(
    user,
    team_id: int,
    *,
    scopes: PosthogMcpScopes = "read_only",
    include_internal_scopes: bool = True,
    application: SandboxOAuthApplication = "array",
) -> str:
    resolved = resolve_scopes(scopes, include_internal_scopes=include_internal_scopes)
    app = get_sandbox_oauth_app(application)
    return _mint_oauth_access_token(user, team_id, app=app, scopes=list(resolved))


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
