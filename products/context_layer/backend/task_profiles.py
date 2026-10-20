from products.tasks.backend.facade.profiles import PrAuthorship, TaskProfile, WarmPolicy, WarmQuota

DREAM = TaskProfile(
    key="context_layer.dream",
    origin_product="user_created",
    billing_product="background_agents",
    listed=False,
    warm=WarmPolicy(quota=WarmQuota.NONE, per_user_cap=10, per_org_cap=100, feature_flag="tasks-prewarm-sandbox"),
    inherit_user_defaults=False,
    personal_mcp=False,
    user_authorable_prs=True,
    default_pr_authorship=PrAuthorship.USER,
    idle_minutes=60,
    max_wake_minutes=None,
)

PROFILES = (DREAM,)
