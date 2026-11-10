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

# The agent explores with execute-sql (query:read, insight:read) and writes only through
# the autoresearch tools. The PostHog MCP server reads /api/users/@me/ to start a session,
# so without user:read it refuses the connection and the agent gets none of those tools.
# The brief carries user-authored text, so the token grants nothing beyond that.
TRAINING_MCP_SCOPES = ["query:read", "insight:read", "user:read", "autoresearch:read", "autoresearch:write"]

# Added only when the report notebook flag is on for the user who starts the run.
# notebook:write also exposes notebooks-partial-update and notebooks-destroy, so the brief
# limits the agent to the notebook it creates in this run.
REPORT_NOTEBOOK_MCP_SCOPES = ["notebook:read", "notebook:write"]

TRAINING = TaskProfile(
    key="autoresearch.training",
    origin_product="autoresearch",
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
    sandbox_templates=("default_base", "autoresearch_base"),
    network=NetworkPolicy(levels=(NetworkAccess.FULL,)),
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent=None,
    mcp_scopes=[*TRAINING_MCP_SCOPES, *REPORT_NOTEBOOK_MCP_SCOPES],
    mcp_store_servers=False,
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

PROFILES = (TRAINING,)


def register() -> None:
    register_task_profiles(PROFILES)
