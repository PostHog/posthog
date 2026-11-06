from products.tasks.backend.facade.profiles import (
    DrivePolicy,
    GithubAccess,
    GithubResolution,
    NetworkAccess,
    NetworkPolicy,
    OAuthApp,
    PrAuthorship,
    Read,
    TaskProfile,
    register_task_profiles,
)

DREAM = TaskProfile(
    key="context_layer.dream",
    origin_product="context_layer",
    public=False,
    public_options=frozenset(),
    source_kind=None,
    listed=False,
    read_without_channel=Read.CREATOR,
    api_visible=True,
    drive=DrivePolicy.OWNER,
    max_live_per_user=None,
    warm=None,
    runtimes=("acp",),
    sandbox_templates=("default_base",),
    network=NetworkPolicy(levels=(NetworkAccess.FULL,)),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes="full",
    mcp_store_servers=True,
    mcp_exclude_tools=(),
    oauth_app=OAuthApp.ARRAY,
    github_resolution=GithubResolution.WITH_REPOSITORY,
    github_access=GithubAccess.WRITE,
    user_authorable_prs=False,
    default_pr_authorship=PrAuthorship.BOT,
    create_pr=True,
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

PROFILES = (DREAM,)


def register() -> None:
    register_task_profiles(PROFILES)
