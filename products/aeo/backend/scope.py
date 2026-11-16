"""Which citation checks a set-level read counts: one side of the branded split, one engine, one topic.

The overview, the rankings and the keyword reports all narrow their checks the same way, so the ORM
filter and the raw SQL predicate live here and stay in step.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from posthog.dataclasses import frozen

from products.aeo.backend.brand import SEGMENT_SQL, brand_regex, segment_filter, segment_sql_params
from products.aeo.backend.facade.contracts import BrandedSegment


@frozen
class CheckScope:
    segment: BrandedSegment = BrandedSegment.ALL
    # None keeps every engine or topic. An empty topic keeps the checks of prompts that had no topic.
    engine: str | None = None
    topic: str | None = None


def scope_filter(scope: CheckScope, target_domains: list[str]) -> Q:
    """`AEOCitationCheck` rows in the scope. The topic is the one the prompt had when the check ran."""
    condition = segment_filter(scope.segment, target_domains)
    if scope.engine is not None:
        condition &= Q(engine=scope.engine)
    if scope.topic is not None:
        condition &= Q(prompt_topic=scope.topic)
    return condition


def scope_without_segment(scope: CheckScope) -> CheckScope:
    return CheckScope(engine=scope.engine, topic=scope.topic)


# `scope_filter` for raw SQL over `posthog_aeo_citation_check AS check_row`, with the parameters from
# `scope_sql_params`. The casts let Postgres type a null parameter.
SCOPE_SQL = (
    f"{SEGMENT_SQL} AND (%s::text IS NULL OR check_row.engine = %s) "
    "AND (%s::text IS NULL OR check_row.prompt_topic = %s)"
)


def scope_sql_params(scope: CheckScope, target_domains: list[str]) -> list[str | None]:
    return [
        *segment_sql_params(scope.segment, target_domains),
        scope.engine,
        scope.engine,
        scope.topic,
        scope.topic,
    ]


# `SCOPE_SQL` for statements that take named parameters, filled from `named_scope_sql_params`.
NAMED_SCOPE_SQL = (
    "(%(scope_segment)s = 'all' OR coalesce(check_row.prompt_text ~* %(scope_brand)s::text, false) = "
    "(%(scope_segment)s = 'branded')) "
    "AND (%(scope_engine)s::text IS NULL OR check_row.engine = %(scope_engine)s) "
    "AND (%(scope_topic)s::text IS NULL OR check_row.prompt_topic = %(scope_topic)s)"
)


def named_scope_sql_params(scope: CheckScope, target_domains: list[str]) -> dict[str, Any]:
    return {
        "scope_segment": scope.segment.value,
        "scope_brand": brand_regex(target_domains),
        "scope_engine": scope.engine,
        "scope_topic": scope.topic,
    }
