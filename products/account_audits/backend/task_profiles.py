from products.tasks.backend.facade.profiles import GithubResolution, TaskProfile

ACCOUNT_AUDIT = TaskProfile(
    key="account_audit",
    origin_product="account_audit",
    billing_product="account_audit",
    listed=False,
    api_visible=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_store_servers=False,
    github_resolution=GithubResolution.NEVER,
)

PROFILES = (ACCOUNT_AUDIT,)
