from products.tasks.backend.facade.profiles import TaskProfile

BUSINESS_KNOWLEDGE = TaskProfile(
    key="business_knowledge",
    origin_product="business_knowledge",
    billing_product="background_agents",
    listed=False,
    api_visible=False,
    inherit_user_defaults=False,
    personal_mcp=False,
)

PROFILES = (BUSINESS_KNOWLEDGE,)
