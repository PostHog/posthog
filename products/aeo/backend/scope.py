"""Which citation checks a set-level read counts: one side of the branded split, one engine, one topic.

The overview, the rankings and the keyword reports all narrow their checks the same way, so the ORM
filter and the raw SQL predicate live here and stay in step.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from posthog.dataclasses import frozen

from products.aeo.backend.brand import SEGMENT_SQL, check_segment_filter, segment_sql_params
from products.aeo.backend.facade.contracts import BrandedSegment


@frozen
class CheckScope:
    segment: BrandedSegment = BrandedSegment.ALL
    # None keeps every engine or topic. An empty topic keeps the checks of prompts that had no topic.
    # A topic matches regardless of letter case, because the topic lists merge such spellings into one.
    engine: str | None = None
    topic: str | None = None
    # Only the checks of prompts that aren't archived, such as the prompts of the current setup after a reset.
    current_prompts: bool = False


def scope_filter(scope: CheckScope) -> Q:
    """`AEOCitationCheck` rows in the scope. The topic is the one the prompt had when the check ran."""
    condition = check_segment_filter(scope.segment)
    if scope.engine is not None:
        condition &= Q(engine=scope.engine)
    if scope.topic is not None:
        condition &= Q(prompt_topic__iexact=scope.topic)
    if scope.current_prompts:
        condition &= Q(prompt__archived_at__isnull=True)
    return condition


def scope_without_segment(scope: CheckScope) -> CheckScope:
    return CheckScope(engine=scope.engine, topic=scope.topic, current_prompts=scope.current_prompts)


# `scope_filter` for raw SQL over `posthog_aeo_citation_check AS check_row`, with the parameters from
# `scope_sql_params`. The casts let Postgres type a null parameter.
SCOPE_SQL = (
    f"{SEGMENT_SQL} AND (%s::text IS NULL OR check_row.engine = %s) "
    "AND (%s::text IS NULL OR upper(check_row.prompt_topic) = upper(%s)) "
    "AND (NOT %s OR EXISTS (SELECT 1 FROM posthog_aeo_prompt AS scope_prompt "
    "WHERE scope_prompt.id = check_row.prompt_id AND scope_prompt.archived_at IS NULL))"
)


def scope_sql_params(scope: CheckScope) -> list[str | bool | None]:
    return [
        *segment_sql_params(scope.segment),
        scope.engine,
        scope.engine,
        scope.topic,
        scope.topic,
        scope.current_prompts,
    ]


# `SCOPE_SQL` for statements that take named parameters, filled from `named_scope_sql_params`.
NAMED_SCOPE_SQL = (
    "(%(scope_segment)s = 'all' OR check_row.prompt_branded = (%(scope_segment)s = 'branded')) "
    "AND (%(scope_engine)s::text IS NULL OR check_row.engine = %(scope_engine)s) "
    "AND (%(scope_topic)s::text IS NULL OR upper(check_row.prompt_topic) = upper(%(scope_topic)s)) "
    "AND (NOT %(scope_current_prompts)s OR EXISTS (SELECT 1 FROM posthog_aeo_prompt AS scope_prompt "
    "WHERE scope_prompt.id = check_row.prompt_id AND scope_prompt.archived_at IS NULL))"
)


def named_scope_sql_params(scope: CheckScope) -> dict[str, Any]:
    return {
        "scope_segment": scope.segment.value,
        "scope_engine": scope.engine,
        "scope_topic": scope.topic,
        "scope_current_prompts": scope.current_prompts,
    }
