from products.tasks.backend.facade.profiles import TaskProfile

SUPPORT_REPLY = TaskProfile(
    key="conversations.support_reply",
    origin_product="support_reply",
    billing_product="conversations",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    mcp_agent="support",
)

PROFILES = (SUPPORT_REPLY,)
