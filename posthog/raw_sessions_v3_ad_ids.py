import re

# Django-free home for the raw-sessions-v3 lower-tier ad-id list. Kept out of
# posthog.models.raw_sessions.sessions_v3 (whose package __init__ boots the Django ORM) so the
# HogQL sessions_v3 schema table can build its field catalog at import without booting Django.
# posthog.models.raw_sessions.sessions_v3 re-exports this for existing callers.

SESSION_V3_LOWER_TIER_AD_IDS = [
    "gclsrc",  # google ads 360
    "dclid",  # google display ads
    "gbraid",  # google ads, web to app
    "wbraid",  # google ads, app to web
    "gad_campaignid",  # google ads campaign id
    "srsltid",  # google merchant center auto-tagging
    "msclkid",  # microsoft
    "twclid",  # twitter
    "li_fat_id",  # linkedin
    "mc_cid",  # mailchimp campaign id
    "igshid",  # instagram
    "ttclid",  # tiktok
    "rdt_cid",  # reddit
    "epik",  # pinterest
    "qclid",  # quora
    "sccid",  # snapchat
    "_kx",  # klaviyo
    "irclid",  # impact (legacy spelling, kept for property parity)
    "irclickid",  # impact
    "utm_id",  # GA4 campaign id
    "utm_source_platform",  # GA4
    "utm_creative_format",  # GA4
    "utm_marketing_tactic",  # GA4
    "yclid",  # yandex
    "tblci",  # taboola
    "dicbo",  # outbrain
    "ndclid",  # nextdoor
    "cjevent",  # cj affiliate
    "awc",  # awin
    "syclid",  # shopify
    "_bhlid",  # beehiiv
    "rtid",  # rokt
]

# URL query-string spellings that differ from the canonical property key. Snapchat documents
# all three casings for its click ID (https://businesshelp.snapchat.com/s/article/click-id).
SESSION_V3_AD_ID_URL_ALIASES: dict[str, list[str]] = {
    "sccid": ["sccid", "ScCid", "SsCid"],
}


def session_ad_id_url_params(ad_id: str) -> list[str]:
    return SESSION_V3_AD_ID_URL_ALIASES.get(ad_id, [ad_id])


# Every entry is interpolated into ClickHouse DDL as a quoted literal and a bare alias, so a
# stray quote or metacharacter in a future entry would become injected DDL. Fail at import.
for _param in SESSION_V3_LOWER_TIER_AD_IDS + [p for aliases in SESSION_V3_AD_ID_URL_ALIASES.values() for p in aliases]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _param):
        raise ValueError(f"ad id {_param!r} is not a safe SQL identifier")
