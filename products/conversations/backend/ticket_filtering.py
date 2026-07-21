"""Shared ticket filter application.

Single implementation behind both the tickets list endpoint and alert-rule
evaluation, so a rule created "from current filters" is guaranteed to count
exactly the tickets the list view shows.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db.models import CharField, Exists, OuterRef, Q, QuerySet
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.models.comment import Comment
from posthog.utils import relative_date_parse

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, ChannelDetail, Priority, Status

if TYPE_CHECKING:
    from posthog.models import Team

MAX_TAG_FILTER_VALUES = 50

# Params that never make sense inside a stored alert-rule filter: the rule's
# window supplies the time bound, and ordering/pagination don't affect counts.
RULE_IGNORED_FILTER_KEYS = frozenset({"date_from", "date_to", "order_by", "limit", "offset", "view"})

# The filter params a stored alert rule may use — everything below that filters
# rows, i.e. the tickets-list params minus the time/ordering ones above.
RULE_ALLOWED_FILTER_KEYS = frozenset(
    {
        "status",
        "priority",
        "channel_source",
        "channel_detail",
        "assignee",
        "distinct_ids",
        "search",
        "sla",
        "snoozed",
        "tags",
        "tags_all",
        "tags_exclude",
        "ai_triage_result",
    }
)


def apply_ticket_filters(queryset: QuerySet[Ticket], params: Mapping[str, str], team: Team) -> QuerySet[Ticket]:
    """Apply tickets-list filter params to a queryset.

    ``params`` uses the query-param string shape of the tickets list endpoint
    (comma-separated multi-values, JSON-encoded tag lists). Unknown keys are
    ignored. Tag filters introduce join fan-out — aggregate with
    ``Count(..., distinct=True)`` or keep the ``.distinct()`` applied here.
    """
    status_param = params.get("status")
    if status_param:
        valid_statuses = [s.value for s in Status]
        statuses = [s.strip() for s in status_param.split(",") if s.strip() in valid_statuses]
        if len(statuses) == 1:
            queryset = queryset.filter(status=statuses[0])
        elif len(statuses) > 1:
            queryset = queryset.filter(status__in=statuses)

    priority_param = params.get("priority")
    if priority_param:
        valid_priorities = [p.value for p in Priority]
        priorities = [p.strip() for p in priority_param.split(",") if p.strip() in valid_priorities]
        if len(priorities) == 1:
            queryset = queryset.filter(priority=priorities[0])
        elif len(priorities) > 1:
            queryset = queryset.filter(priority__in=priorities)

    channel_source = params.get("channel_source")
    if channel_source and channel_source in [c.value for c in Channel]:
        queryset = queryset.filter(channel_source=channel_source)

    channel_detail = params.get("channel_detail")
    if channel_detail and channel_detail in [d.value for d in ChannelDetail]:
        queryset = queryset.filter(channel_detail=channel_detail)

    assignee_param = params.get("assignee")
    if assignee_param:
        user_ids: list[int] = []
        role_ids: list[uuid.UUID] = []
        include_unassigned = False
        for raw_entry in assignee_param.split(",")[:100]:
            entry = raw_entry.strip()
            if entry.lower() == "unassigned":
                include_unassigned = True
            elif entry.startswith("user:"):
                try:
                    user_ids.append(int(entry[5:]))
                except ValueError:
                    pass
            elif entry.startswith("role:"):
                try:
                    role_ids.append(uuid.UUID(entry[5:]))
                except (ValueError, AttributeError):
                    pass
        assignee_q = Q()
        if user_ids:
            assignee_q |= Q(assignment__user_id__in=user_ids)
        if role_ids:
            assignee_q |= Q(assignment__role_id__in=role_ids)
        if include_unassigned:
            assignee_q |= Q(assignment__isnull=True)
        if assignee_q:
            queryset = queryset.filter(assignee_q)

    date_from = params.get("date_from")
    if date_from and date_from != "all":
        parsed = relative_date_parse(date_from, team.timezone_info)
        if parsed:
            queryset = queryset.filter(updated_at__gte=parsed)

    date_to = params.get("date_to")
    if date_to:
        parsed = relative_date_parse(date_to, team.timezone_info)
        if parsed:
            queryset = queryset.filter(updated_at__lte=parsed)

    distinct_ids_param = params.get("distinct_ids")
    if distinct_ids_param:
        ids = [id.strip() for id in distinct_ids_param.split(",") if id.strip()][:100]
        if ids:
            queryset = queryset.filter(distinct_id__in=ids)

    search = params.get("search")
    if search and len(search) <= 200:
        if search.isdigit():
            queryset = queryset.filter(ticket_number=int(search))
        else:
            # EXISTS subquery: matches any comment in the ticket's conversation.
            # Uses the (team_id, scope, item_id) composite index on Comment to
            # narrow to per-ticket comments; EXISTS short-circuits on first match.
            # If this becomes slow at scale (10k+ candidate tickets with broad
            # filters), consider adding a GIN trigram index on Comment.content:
            #   GinIndex(name="comment_content_trigram", fields=["content"],
            #            opclasses=["gin_trgm_ops"])
            comment_match = Comment.objects.filter(
                team_id=OuterRef("team_id"),
                scope="conversations_ticket",
                item_id=Cast(OuterRef("id"), output_field=CharField()),
                content__icontains=search,
                deleted=False,
            )
            queryset = queryset.filter(
                Q(anonymous_traits__name__icontains=search)
                | Q(anonymous_traits__email__icontains=search)
                | Q(email_subject__icontains=search)
                | Exists(comment_match)
            )

    sla_param = params.get("sla")
    if sla_param:
        now = timezone.now()
        if sla_param == "breached":
            queryset = queryset.filter(sla_due_at__lt=now)
        elif sla_param == "at-risk":
            queryset = queryset.filter(sla_due_at__gte=now, sla_due_at__lte=now + timedelta(hours=1))
        elif sla_param == "on-track":
            queryset = queryset.filter(sla_due_at__gt=now + timedelta(hours=1))

    snoozed_param = params.get("snoozed")
    if snoozed_param is not None:
        if snoozed_param.lower() == "true":
            queryset = queryset.filter(snoozed_until__isnull=False)
        elif snoozed_param.lower() == "false":
            queryset = queryset.filter(snoozed_until__isnull=True)

    tags_param = params.get("tags")
    if tags_param:
        try:
            tags_list = json.loads(tags_param)
            if isinstance(tags_list, list) and tags_list:
                queryset = queryset.filter(tagged_items__tag__name__in=tags_list[:MAX_TAG_FILTER_VALUES]).distinct()
        except json.JSONDecodeError:
            pass

    tags_all_param = params.get("tags_all")
    if tags_all_param:
        try:
            tags_all_list = json.loads(tags_all_param)
            if isinstance(tags_all_list, list) and tags_all_list:
                # One filter per tag (not __in) so this is AND: the ticket must carry every tag.
                for tag_name in tags_all_list[:MAX_TAG_FILTER_VALUES]:
                    queryset = queryset.filter(tagged_items__tag__name=tag_name)
                queryset = queryset.distinct()
        except json.JSONDecodeError:
            pass

    tags_exclude_param = params.get("tags_exclude")
    if tags_exclude_param:
        try:
            tags_exclude_list = json.loads(tags_exclude_param)
            if isinstance(tags_exclude_list, list) and tags_exclude_list:
                queryset = queryset.exclude(tagged_items__tag__name__in=tags_exclude_list[:MAX_TAG_FILTER_VALUES])
        except json.JSONDecodeError:
            pass

    ai_triage_result_param = params.get("ai_triage_result")
    if ai_triage_result_param:
        valid_results = {
            "persisted",
            "escalated_with_best",
            "escalated_no_reply",
            "skipped_unactionable",
            "blocked_unsafe",
            "blocked_unsafe_reply",
            "in_progress",
        }
        results = {r.strip() for r in ai_triage_result_param.split(",") if r.strip() in valid_results}
        if results:
            q = Q()
            normal_results = results - {"in_progress"}
            if normal_results:
                q |= Q(ai_triage__result__in=normal_results)
            if "in_progress" in results:
                q |= Q(ai_triage__status="in_progress")
            queryset = queryset.filter(q)

    return queryset


def rule_filter_params(filters: Mapping[str, str]) -> dict[str, str]:
    """Sanitize a stored rule's filters for evaluation: keep only string values
    and drop time/ordering params that would fight the rule's own window."""
    return {
        key: value
        for key, value in filters.items()
        if key not in RULE_IGNORED_FILTER_KEYS and isinstance(value, str) and value
    }
