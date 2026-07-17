# Django-free home for the raw-sessions-v3 lower-tier ad-id list. Kept out of
# posthog.models.raw_sessions.sessions_v3 (whose package __init__ boots the Django ORM) so the
# HogQL sessions_v3 schema table can build its field catalog at import without booting Django.
# posthog.models.raw_sessions.sessions_v3 re-exports this for existing callers.

SESSION_V3_LOWER_TIER_AD_IDS = [
    "gclsrc",
    "dclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "twclid",
    "li_fat_id",
    "mc_cid",
    "igshid",
    "ttclid",
    "epik",
    "qclid",
    "sccid",
    "_kx",
    "irclid",
]
