from __future__ import annotations

import secrets
from typing import Any

# Aliased to dodge a Semgrep rule that flags `Group.objects` as a
# persons-DB access pattern. This Group is django.contrib.auth.models.Group,
# which lives in the default DB.
from django.contrib.auth.models import Group as AuthGroup
from django.core.management.base import BaseCommand

from posthog.models.data_color_theme import DataColorTheme
from posthog.models.oauth import OAuthApplication

from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.demo.backend.facade.api import seed_dev_dashboard_templates
from products.growth.backend.models import EnrichmentPromptConfig

# auth groups originally seeded by RunPython migrations. Keep this in sync with
# any 04xx/05xx migration that did `AuthGroup.objects.get_or_create(name=...)`.
_AUTH_GROUPS: tuple[str, ...] = ("Billing Team", "ClickHouse Team")

# Streamlit OAuth first-party app — mirrors
# products/streamlit_apps/backend/migrations/0002_seed_streamlit_oauth_app.py.
# Folded into the squash, so a fresh DB needs this seed to keep the
# Streamlit Apps token-minting path working.
_STREAMLIT_OAUTH_APP_NAME = "PostHog Streamlit Apps"
_STREAMLIT_OAUTH_CLIENT_ID = "posthog-streamlit-apps-first-party"

# Default theme colors originally seeded by migration 0537. Inlined (not
# imported from the migration module) so this command survives squash
# retirement, which deletes replaced migration files.
_DEFAULT_THEME_COLORS: list[str] = [
    "#1d4aff",
    "#621da6",
    "#42827e",
    "#ce0e74",
    "#f14f58",
    "#7c440e",
    "#529a0a",
    "#0476fb",
    "#fe729e",
    "#35416b",
    "#41cbc4",
    "#b64b02",
    "#e4a604",
    "#a56eff",
    "#30d5c8",
]

# The ai_pilled enrichment prompt config originally seeded by growth migration
# 0006. Without it a fresh database has no active label for the growth
# enrichment commands to run. Iteration happens via new EnrichmentPromptConfig
# rows in Django admin, never by editing this seed.
_AI_PILLED_CLAY_V1_PROMPT = """\
You classify whether a company is an "AI-pilled software team" from a signup email domain, for PostHog onboarding routing.
AI-pilled = a company that builds software as its product, ships AI-first, uses modern AI dev tools, and has or is chasing real revenue or venture funding. This INCLUDES startups in any vertical (fintech, ops, healthcare, legal, recruiting, etc.) as long as they build their own software with an engineering team. Think YC-to-IPO startups and dev/AI companies (e.g. Supabase, ElevenLabs, Ramp, Mercury, Vercel).
NOT ai-pilled = companies that don't build software as their core product: traditional/non-tech businesses, agencies, consultancies, brick-and-mortar, and large non-technical enterprises. Also hobbyists and generic free-email signups (gmail.com, outlook.com, etc.) where the company is unknown.
Do NOT disqualify a company just because its industry is finance, ops, or recruiting. Judge on "do they build software with engineers," not the vertical.
Judge only from the domain and what you know about that company. If you don't recognize it, infer from the domain name; if there's no signal, return false with low confidence.
Email domain: {email}"""

_AI_PILLED_INPUT_FIELDS = [
    "name",
    "description",
    "website.url",
    "companyType",
    "headcount",
    "tagsV2",
    "funding.fundingStage",
    "location.country",
]

_AI_PILLED_OUTPUT_FIELDS = [
    {"key": "ai_pilled", "type": "boolean", "description": "Whether the company is ai_pilled."},
    {"key": "confidence", "type": "number", "description": "0-1 confidence in the verdict."},
    {"key": "reasoning", "type": "string", "description": "One short sentence."},
]

# Template data originally from migrations 0310 and 0328.
# Cannot call those migration functions directly because they use
# apps.get_model("posthog", "DashboardTemplate") which no longer
# resolves after the model moved to the dashboards product app.
# Tiles carry `query`, unlike the legacy `filters` those migrations wrote:
# `create_from_template` builds each insight from `query` alone, so a
# filters-shaped tile yields an insight with no definition at all.
_PRODUCT_ANALYTICS_TEMPLATE: dict[str, Any] = {
    "template_name": "Product analytics",
    "dashboard_description": (
        "High-level overview of your product including daily active users, "
        "weekly active users, retention, and growth accounting."
    ),
    "dashboard_filters": {},
    "tiles": [
        {
            "name": "Daily active users (DAUs)",
            "type": "INSIGHT",
            "color": "blue",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "dau"}],
                    "dateRange": {"date_from": "-30d"},
                    "trendsFilter": {},
                    "breakdownFilter": {},
                    "compareFilter": {},
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
            },
            "description": "Shows the number of unique users that use your app every day.",
        },
        {
            "name": "Weekly active users (WAUs)",
            "type": "INSIGHT",
            "color": "green",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "dau"}],
                    "dateRange": {"date_from": "-90d"},
                    "interval": "week",
                    "trendsFilter": {},
                    "breakdownFilter": {},
                    "compareFilter": {},
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
            },
            "description": "Shows the number of unique users that use your app every week.",
        },
        {
            "name": "Retention",
            "type": "INSIGHT",
            "color": "blue",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "RetentionQuery",
                    "dateRange": {},
                    "retentionFilter": {
                        "period": "Week",
                        "retentionType": "retention_first_time",
                        "targetEntity": {"id": "$pageview", "type": "events"},
                        "returningEntity": {"id": "$pageview", "type": "events"},
                        "meanRetentionCalculation": "simple",
                    },
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 10, "minH": 5, "minW": 3},
            },
            "description": "Weekly retention of your users.",
        },
        {
            "name": "Growth accounting",
            "type": "INSIGHT",
            "color": "purple",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "LifecycleQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview"}],
                    "dateRange": {"date_from": "-30d"},
                    "interval": "week",
                    "lifecycleFilter": {},
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 3},
            },
            "description": "How many of your users are new, returning, resurrecting, or dormant each week.",
        },
        {
            "name": "Referring domain (last 14 days)",
            "type": "INSIGHT",
            "color": "black",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "dau"}],
                    "dateRange": {"date_from": "-14d"},
                    "breakdownFilter": {"breakdown": "$referring_domain"},
                    "trendsFilter": {"display": "ActionsBarValue"},
                    "compareFilter": {},
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 0, "y": 10, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 20, "minH": 5, "minW": 3},
            },
            "description": "Shows the most common referring domains for your users over the past 14 days.",
        },
        {
            "name": "Pageview funnel, by browser",
            "type": "INSIGHT",
            "color": "green",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "FunnelsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "name": "$pageview",
                            "custom_name": "First page view",
                        },
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "name": "$pageview",
                            "custom_name": "Second page view",
                        },
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "name": "$pageview",
                            "custom_name": "Third page view",
                        },
                    ],
                    "dateRange": {},
                    "interval": "day",
                    "breakdownFilter": {"breakdown": "$browser"},
                    "funnelsFilter": {"layout": "horizontal"},
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 10, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 25, "minH": 5, "minW": 3},
            },
            "description": "This example funnel shows how many of your users have completed 3 page views, broken down by browser.",
        },
    ],
    "tags": [],
    "scope": "global",
}

_FEATURE_FLAG_TEMPLATE: dict[str, Any] = {
    "template_name": "Flagged Feature Usage",
    "dashboard_description": (
        "Overview of engagement with the flagged feature including daily active users and weekly active users."
    ),
    "dashboard_filters": {},
    # `{ENGAGEMENT}` stands in for a series entry. The browser resolves it against
    # the variable below before the tiles reach the API, so no placeholder is stored.
    "tiles": [
        {
            "name": "Daily active users (DAUs)",
            "type": "INSIGHT",
            "color": "blue",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": ["{ENGAGEMENT}"],
                    "dateRange": {"date_from": "-30d"},
                    "trendsFilter": {},
                    "breakdownFilter": {},
                    "compareFilter": {},
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
            },
            "description": "Shows the number of unique users that use your feature every day.",
        },
        {
            "name": "Weekly active users (WAUs)",
            "type": "INSIGHT",
            "color": "green",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": ["{ENGAGEMENT}"],
                    "dateRange": {"date_from": "-90d"},
                    "interval": "week",
                    "trendsFilter": {},
                    "breakdownFilter": {},
                    "compareFilter": {},
                },
            },
            "layouts": {
                "sm": {"h": 5, "w": 6, "x": 6, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
            },
            "description": "Shows the number of unique users that use your feature every week.",
        },
    ],
    "tags": [],
    "variables": [
        {
            "id": "ENGAGEMENT",
            "name": "Engagement",
            "type": "event",
            "default": {"name": "$pageview", "id": "$pageview"},
            "required": True,
            "description": "The event you use to define a user using the new feature",
        }
    ],
    "scope": "feature_flag",
}


class Command(BaseCommand):
    help = "Ensure default data from migrations exists for schema-only restores."

    def handle(self, *args: Any, **options: Any) -> None:
        created_items: list[str] = []

        for group_name in _AUTH_GROUPS:
            _, created = AuthGroup.objects.get_or_create(name=group_name)
            if created:
                created_items.append(f"Auth group: {group_name}")

        if not DataColorTheme.objects.filter(team__isnull=True, name="Default Theme").exists():
            DataColorTheme.objects.create(name="Default Theme", colors=_DEFAULT_THEME_COLORS)
            created_items.append("Data color theme: Default Theme")

        # Same two-step shape as growth migration 0006: insert inactive so the
        # growth_prompt_config_one_active constraint can't collide, promote only
        # when no other active config exists.
        ai_pilled, _ = EnrichmentPromptConfig.objects.get_or_create(
            name="ai_pilled",
            version="ai-pilled-clay-v1",
            defaults={
                "prompt_text": _AI_PILLED_CLAY_V1_PROMPT,
                "model": "gpt-5-mini",
                "input_fields": _AI_PILLED_INPUT_FIELDS,
                "output_fields": _AI_PILLED_OUTPUT_FIELDS,
                "is_active": False,
            },
        )
        other_active_exists = (
            EnrichmentPromptConfig.objects.filter(name="ai_pilled", is_active=True).exclude(pk=ai_pilled.pk).exists()
        )
        if not ai_pilled.is_active and not other_active_exists:
            ai_pilled.is_active = True
            ai_pilled.save(update_fields=["is_active"])
            created_items.append("Growth enrichment prompt config: ai_pilled")

        if not OAuthApplication.objects.filter(client_id=_STREAMLIT_OAUTH_CLIENT_ID).exists():
            OAuthApplication.objects.create(
                name=_STREAMLIT_OAUTH_APP_NAME,
                client_id=_STREAMLIT_OAUTH_CLIENT_ID,
                client_secret=secrets.token_urlsafe(48),
                client_type="confidential",
                authorization_grant_type="authorization-code",
                redirect_uris="https://localhost",
                algorithm="RS256",
                is_first_party=True,
            )
            created_items.append(f"OAuth app: {_STREAMLIT_OAUTH_APP_NAME}")

        for template_data in (_PRODUCT_ANALYTICS_TEMPLATE, _FEATURE_FLAG_TEMPLATE):
            name = template_data["template_name"]
            if not DashboardTemplate.objects.filter(template_name=name, team__isnull=True).exists():
                DashboardTemplate.objects.create(**template_data)
                created_items.append(f"Dashboard template: {name}")

        for name in seed_dev_dashboard_templates():
            created_items.append(f"Dashboard template: {name}")

        if created_items:
            self.stdout.write("Created defaults:\n- " + "\n- ".join(created_items))
        else:
            self.stdout.write("Default migration data already present.")
