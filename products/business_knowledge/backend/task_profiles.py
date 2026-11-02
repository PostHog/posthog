from products.tasks.backend.facade.profiles import (
    AccessGate,
    DrivePolicy,
    GithubResolution,
    NetworkAccess,
    NetworkPolicy,
    OAuthApp,
    PrAuthorship,
    Read,
    TaskProfile,
    register_task_profiles,
)

from .constants import BK_MCP_SCOPES, MAX_OPEN_RUNS_PER_OWNER

BUSINESS_KNOWLEDGE = TaskProfile(
    key="business_knowledge",
    origin_product="business_knowledge",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=False,
    read_without_channel=Read.CREATOR,
    api_visible=False,
    drive=DrivePolicy.OWNER,
    access_gate=AccessGate.NONE,
    max_live_per_user=MAX_OPEN_RUNS_PER_OWNER,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.CUSTOM,)),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes=BK_MCP_SCOPES,
    mcp_store_servers=False,
    oauth_app=OAuthApp.ARRAY,
    github_resolution=GithubResolution.ALWAYS,
    user_authorable_prs=False,
    default_pr_authorship=PrAuthorship.BOT,
    create_pr=False,
    finish_tool=False,
    done_on_turn_close=False,
    idle_minutes=30,
    inactivity_minutes=10,
    tool_call_minutes=None,
    max_wake_minutes=180,
    billing_product="background_agents",
    bills_compute=False,
    max_cost_usd=None,
    task_budget_usd=None,
    finish_in_flight=True,
)

PROFILES = (BUSINESS_KNOWLEDGE,)


def register() -> None:
    register_task_profiles(PROFILES)
