"""Insight noise + lookup seeder for retrieval evals.

Bulk-creates ``NOISE_INSIGHT_COUNT`` plausible-looking insights plus a
small set of distinctive lookup insights. The lookup names are
deterministic, so an eval prompt can hard-code one verbatim and the
``LookupIdInOutput`` scorer can match the prompt back to the seeded ID.
"""

from __future__ import annotations

import logging
from typing import Any

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext

from ee.hogai.eval.sandboxed.seeders.common import LOOKUP_PREFIX, NameProviders, make_name_providers

logger = logging.getLogger(__name__)


__all__ = [
    "seed_insight_noise",
    "LOOKUP_NAMES",
    "FUZZY_LOOKUP_NAMES",
    "ALL_LOOKUP_NAMES",
    "NOISE_INSIGHT_COUNT",
]


# Deterministic lookup names referenced verbatim by retrieval prompts.
# The ``[lookup]`` prefix guarantees no collision with the noise generator
# and lets prompts unambiguously name the target insight.
LOOKUP_NAMES: list[str] = [
    f"{LOOKUP_PREFIX} Northern Lights Funnel",
    f"{LOOKUP_PREFIX} Aurora Retention Cohort",
    f"{LOOKUP_PREFIX} Solstice Pageview Trend",
]

# Plausible-looking insight names without the ``[lookup]`` prefix, used by
# fuzzy-retrieval cases where the prompt describes the insight in natural
# language (e.g. "MAUs") rather than naming it verbatim. The format
# (parentheses + brand) cannot be produced by the noise generator, so
# collisions are still impossible.
FUZZY_LOOKUP_NAMES: list[str] = [
    "Monthly Active Users (Hedgebox)",
]

ALL_LOOKUP_NAMES: list[str] = [*LOOKUP_NAMES, *FUZZY_LOOKUP_NAMES]

NOISE_INSIGHT_COUNT = 1000

# Static query shapes recycled round-robin across the noise insights.
# These don't need to be queryable — they just need to be valid JSON in
# the ``query`` field so the row passes the model layer.
_STATIC_QUERIES: list[dict[str, Any]] = [
    {"kind": "TrendsQuery", "series": [{"event": "$pageview", "kind": "EventsNode"}]},
    {"kind": "TrendsQuery", "series": [{"event": "$identify", "kind": "EventsNode"}]},
    {
        "kind": "FunnelsQuery",
        "series": [
            {"event": "$pageview", "kind": "EventsNode"},
            {"event": "signed_up", "kind": "EventsNode"},
        ],
    },
    {"kind": "RetentionQuery", "retentionFilter": {"period": "Week"}},
]

_METRIC_WORDS = [
    "Daily",
    "Weekly",
    "Monthly",
    "Active",
    "New",
    "Returning",
    "Cumulative",
    "Average",
    "Median",
    "Total",
]
_NOUN_WORDS = [
    "Users",
    "Sessions",
    "Pageviews",
    "Events",
    "Conversions",
    "Signups",
    "Logins",
    "Visits",
    "Clicks",
    "Downloads",
]


def _generate_noise_names(count: int, providers: NameProviders) -> list[str]:
    """Build ``count`` distinct, plausible-looking insight names.

    Names blend a metric verb, a noun, a free-form word, and an
    occupation so they look real but don't collide with the
    ``[lookup]``-prefixed names the prompts ask the agent to find.
    """
    names: set[str] = set()
    while len(names) < count:
        metric = providers.rnd.choice(_METRIC_WORDS)
        noun = providers.rnd.choice(_NOUN_WORDS)
        flavor = providers.text.word().capitalize()
        occupation = providers.person.occupation()
        candidate = f"{metric} {noun} - {flavor} {occupation}"
        if candidate.startswith(LOOKUP_PREFIX):
            continue
        names.add(candidate)
    return list(names)[:count]


def seed_insight_noise(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed ``NOISE_INSIGHT_COUNT`` noise insights plus the lookup insights.

    Returns the lookup insight metadata so ``LookupIdInOutput`` can grade
    whether the agent found the right one. Synchronous — runs in a worker
    thread via ``asyncio.to_thread`` from ``base.py:task()``.
    """
    from posthog.models.insight import Insight

    team_id = context.team_id
    user_id = context.user_id

    providers = make_name_providers()
    noise_names = _generate_noise_names(NOISE_INSIGHT_COUNT, providers)
    noise_objects = [
        Insight(
            team_id=team_id,
            created_by_id=user_id,
            name=name,
            description="",
            saved=True,
            query=_STATIC_QUERIES[i % len(_STATIC_QUERIES)],
        )
        for i, name in enumerate(noise_names)
    ]
    Insight.objects.bulk_create(noise_objects, batch_size=500, ignore_conflicts=True)

    lookup_insights = [
        Insight.objects.create(
            team_id=team_id,
            created_by_id=user_id,
            name=name,
            description="",
            saved=True,
            query=_STATIC_QUERIES[i % len(_STATIC_QUERIES)],
        )
        for i, name in enumerate(ALL_LOOKUP_NAMES)
    ]

    payload: dict[str, Any] = {
        "noise_count": len(noise_objects),
        "lookup_insights": [{"id": ins.id, "short_id": ins.short_id, "name": ins.name} for ins in lookup_insights],
    }
    logger.info(
        "Seeded retrieval noise for team_id=%s: %d noise + %d lookup insights",
        team_id,
        payload["noise_count"],
        len(lookup_insights),
    )
    return payload
