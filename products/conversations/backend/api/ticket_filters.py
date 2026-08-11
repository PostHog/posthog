"""Canonical ticket filter shape and the single place it becomes ORM predicates.

`TicketViewFiltersSerializer` is the source of truth for the saved-view filter
contract: it validates writes to `TicketView.filters`, is what the `?view=`
param validates stored blobs against, and generates the frontend TypeScript and
MCP schemas via OpenAPI. `apply_ticket_filters` is the only implementation of
filtering, fed by two adapters: validated view filters, and the flat snake_case
query params (`query_params_to_view_filters`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db.models import CharField, F, OrderBy, Q, QuerySet
from django.db.models.functions import Cast
from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.models.comment import Comment
from posthog.utils import relative_date_parse

from products.conversations.backend.models.constants import Channel, Priority, Status

if TYPE_CHECKING:
    from posthog.models import Team, User

MAX_TAG_FILTER_VALUES = 50
# Matches MAX_ASSIGNEE_FILTER_ENTRIES in products/conversations/frontend/components/Assignee.
MAX_ASSIGNEE_FILTER_ENTRIES = 100
MAX_SEARCH_LENGTH = 200

SLA_FILTER_VALUES = ["breached", "at-risk", "on-track"]
AI_TRIAGE_FILTER_VALUES = [
    "persisted",
    "escalated_with_best",
    "escalated_no_reply",
    "skipped_unactionable",
    "blocked_unsafe",
    "blocked_unsafe_reply",
    "in_progress",
]

ALLOWED_ORDER_COLUMNS = ("updated_at", "sla_due_at", "snoozed_until", "created_at", "ticket_number")

VALID_STATUS_VALUES = frozenset(s.value for s in Status)
VALID_PRIORITY_VALUES = frozenset(p.value for p in Priority)
VALID_CHANNEL_VALUES = frozenset(c.value for c in Channel)

# Named choice sets for ChoiceFields below, registered in ENUM_NAME_OVERRIDES
# (posthog/settings/web.py) so drf-spectacular doesn't mint generic globals like
# ChannelEnum/SlaEnum/OrderEnum in the shared OpenAPI namespace.
TICKET_CHANNEL_FILTER_CHOICES = [*(c.value for c in Channel), "all"]
TICKET_SLA_FILTER_CHOICES = [*SLA_FILTER_VALUES, "all"]
TICKET_TAGS_MATCH_CHOICES = ["any", "all"]
# Tuple pairs, not bare ints: drf-spectacular's override loader only accepts strings
# in plain value lists and crashes on anything else.
TICKET_SORT_ORDER_CHOICES = [(1, 1), (-1, -1)]


def _is_assignee_entry(value: Any) -> bool:
    if value in ("unassigned", "me"):
        return True
    if not isinstance(value, dict):
        return False
    entry_id = value.get("id")
    if not isinstance(entry_id, str | int) or isinstance(entry_id, bool):
        return False
    # The id must resolve to a real user pk / role UUID: an unresolvable entry would
    # silently apply no filter at query time, widening results past what was asked for.
    if value.get("type") == "user":
        try:
            int(entry_id)
        except (TypeError, ValueError):
            return False
        return True
    if value.get("type") == "role":
        try:
            uuid.UUID(str(entry_id))
        except ValueError:
            return False
        return True
    return False


def normalize_assignee_filter(value: Any) -> list[Any]:
    """Mirrors the frontend's normalizeAssigneeFilter: accepts the current array shape or
    the legacy single-value shape ('all', 'unassigned', or one assignee object) still
    present in old saved views, keeping only valid entries."""
    entries = value if isinstance(value, list) else [value]
    return [entry for entry in entries if _is_assignee_entry(entry)][:MAX_ASSIGNEE_FILTER_ENTRIES]


@extend_schema_field(
    {
        "type": "array",
        "items": {
            "oneOf": [
                {"type": "string", "enum": ["me", "unassigned"]},
                {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["user", "role"]},
                        "id": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                    },
                    "required": ["type", "id"],
                },
            ]
        },
        "description": (
            "Assignees to match (any of): 'unassigned', 'me' (resolved to the requesting user), "
            "or an object with type ('user' or 'role') and id."
        ),
    }
)
class TicketViewAssigneeFilterField(serializers.Field):
    """Lenient by default so legacy stored blobs still apply (an unrecognized entry is
    dropped, and the legacy 'all' sentinel means no filter). Writes pass
    context={"strict_writes": True}: silently dropping a malformed entry there would
    save a view that quietly matches more assignees than the caller asked for."""

    def to_internal_value(self, data: Any) -> list[Any]:
        if self.context.get("strict_writes"):
            entries = data if isinstance(data, list) else [data]
            if any(not _is_assignee_entry(entry) and entry != "all" for entry in entries):
                raise serializers.ValidationError(
                    "Each assignee entry must be 'me', 'unassigned', or an object with type ('user' or 'role') and id."
                )
        return normalize_assignee_filter(data)

    def to_representation(self, value: Any) -> Any:
        return value


class TicketViewSortingSerializer(serializers.Serializer):
    columnKey = serializers.CharField(
        help_text=f"Ticket column to sort by ({', '.join(ALLOWED_ORDER_COLUMNS)}). "
        "Unknown columns fall back to updated_at."
    )
    order = serializers.ChoiceField(choices=TICKET_SORT_ORDER_CHOICES, help_text="1 for ascending, -1 for descending.")


class TicketViewFiltersSerializer(serializers.Serializer):
    """Canonical shape of a saved ticket view's filters. Every field is optional; an omitted
    field (or an 'all' sentinel) leaves that dimension unfiltered."""

    status = serializers.ListField(
        child=serializers.ChoiceField(choices=Status.choices),
        required=False,
        help_text="Ticket statuses to include. Empty or omitted means all statuses.",
    )
    priority = serializers.ListField(
        child=serializers.ChoiceField(choices=Priority.choices),
        required=False,
        help_text="Ticket priorities to include. Empty or omitted means all priorities.",
    )
    channel = serializers.ChoiceField(
        choices=TICKET_CHANNEL_FILTER_CHOICES,
        required=False,
        help_text="Channel the ticket originated from. 'all' disables the filter.",
    )
    sla = serializers.ChoiceField(
        choices=TICKET_SLA_FILTER_CHOICES,
        required=False,
        help_text="SLA state: 'breached' is past due, 'at-risk' is due within the next hour, "
        "'on-track' has more than an hour remaining. 'all' disables the filter.",
    )
    aiTriageResult = serializers.ListField(
        child=serializers.ChoiceField(choices=AI_TRIAGE_FILTER_VALUES),
        required=False,
        help_text="AI triage outcomes to include. 'in_progress' matches tickets still being triaged.",
    )
    assignee = TicketViewAssigneeFilterField(
        required=False,
        help_text="Assignees to match (any of): 'unassigned', 'me' (resolved to the requesting user), "
        "or an object with type ('user' or 'role') and id. The legacy single-value shape is accepted "
        "and normalized to a list.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tag names to match, combined according to tagsMatch.",
    )
    tagsMatch = serializers.ChoiceField(
        choices=TICKET_TAGS_MATCH_CHOICES,
        required=False,
        help_text="'any' returns tickets with at least one of tags (OR); 'all' requires every tag (AND).",
    )
    tagsExclude = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tickets carrying any of these tags are excluded.",
    )
    dateFrom = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Only include tickets updated on or after this date. Accepts absolute dates (2026-01-01) "
        "or relative ones (-7d). 'all' or null disables the bound.",
    )
    dateTo = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Only include tickets updated on or before this date. Same format as dateFrom.",
    )
    sorting = TicketViewSortingSerializer(required=False, allow_null=True, help_text="Sort order for the ticket list.")
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_SEARCH_LENGTH,
        help_text="Free-text search. A numeric value matches a ticket number exactly; otherwise matches "
        "the customer's name or email, the email subject, or message content.",
    )


def _salvage_list_entries(key: str, value: Any) -> list[Any] | None:
    """Keep the individually-valid entries of an errored list value, so one bad legacy
    entry narrows the filter to the valid rest instead of dropping the key (widening)."""
    field = TicketViewFiltersSerializer().fields.get(key)
    if not isinstance(field, serializers.ListField) or not isinstance(value, list):
        return None
    valid_entries = []
    for entry in value:
        try:
            field.child.run_validation(entry)
        except serializers.ValidationError:
            continue
        valid_entries.append(entry)
    return valid_entries or None


def parse_stored_view_filters(stored: Any) -> dict[str, Any]:
    """Leniently validate a stored TicketView.filters blob into the canonical shape.

    Stored blobs predate write validation, so a legacy value must not make the view
    unusable: invalid list entries and offending keys are dropped and the rest still
    apply."""
    if not isinstance(stored, dict):
        return {}
    serializer = TicketViewFiltersSerializer(data=stored)
    if not serializer.is_valid():
        cleaned: dict[str, Any] = {}
        for key, value in stored.items():
            if key not in serializer.errors:
                cleaned[key] = value
            elif (salvaged := _salvage_list_entries(key, value)) is not None:
                cleaned[key] = salvaged
        serializer = TicketViewFiltersSerializer(data=cleaned)
        serializer.is_valid()
    return dict(serializer.validated_data)


def _decode_assignee_param(raw: str) -> list[Any]:
    entries: list[Any] = []
    for raw_entry in raw.split(",")[:MAX_ASSIGNEE_FILTER_ENTRIES]:
        entry = raw_entry.strip()
        if entry.lower() in ("unassigned", "me"):
            entries.append(entry.lower())
        elif entry.startswith("user:"):
            entries.append({"type": "user", "id": entry[5:]})
        elif entry.startswith("role:"):
            entries.append({"type": "role", "id": entry[5:]})
    return [entry for entry in entries if _is_assignee_entry(entry)]


def _decode_json_tag_list(raw: str) -> list[str] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(value, list) and value:
        return [str(tag) for tag in value]
    return None


def _order_by_to_sorting(order_by: str) -> dict[str, Any] | None:
    column = order_by.removeprefix("-")
    if column not in ALLOWED_ORDER_COLUMNS:
        return None
    return {"columnKey": column, "order": -1 if order_by.startswith("-") else 1}


def query_params_to_view_filters(params: Mapping[str, str]) -> dict[str, Any]:
    """Translate the flat snake_case ticket-list query params into the canonical
    TicketViewFilters shape. Only keys whose param is present are set, so values coming
    from a saved view survive unless explicitly overridden. Invalid values are dropped
    rather than rejected, matching the endpoint's long-standing behavior."""
    filters: dict[str, Any] = {}

    # Guard every list on being non-empty: a param whose values all parse away must not
    # set the key, or merging onto a saved view would clear that filter and widen results.
    status_param = params.get("status")
    if status_param:
        statuses = [s.strip() for s in status_param.split(",") if s.strip() in VALID_STATUS_VALUES]
        if statuses:
            filters["status"] = statuses

    priority_param = params.get("priority")
    if priority_param:
        priorities = [p.strip() for p in priority_param.split(",") if p.strip() in VALID_PRIORITY_VALUES]
        if priorities:
            filters["priority"] = priorities

    channel_source = params.get("channel_source")
    if channel_source and channel_source in VALID_CHANNEL_VALUES:
        filters["channel"] = channel_source

    sla_param = params.get("sla")
    if sla_param and sla_param in SLA_FILTER_VALUES:
        filters["sla"] = sla_param

    ai_triage_result_param = params.get("ai_triage_result")
    if ai_triage_result_param:
        results = [r.strip() for r in ai_triage_result_param.split(",") if r.strip() in AI_TRIAGE_FILTER_VALUES]
        if results:
            filters["aiTriageResult"] = results

    assignee_param = params.get("assignee")
    if assignee_param:
        assignees = _decode_assignee_param(assignee_param)
        if assignees:
            filters["assignee"] = assignees

    tags_param = params.get("tags")
    if tags_param:
        tags = _decode_json_tag_list(tags_param)
        if tags:
            filters["tags"] = tags
            filters["tagsMatch"] = "any"

    tags_all_param = params.get("tags_all")
    if tags_all_param:
        tags = _decode_json_tag_list(tags_all_param)
        if tags:
            # Separate key from tags/tagsMatch so tags= and tags_all= compose (AND)
            # instead of the later param clobbering the earlier one. Deliberately NOT
            # part of the saved-view serializer contract: the app can't render a
            # tagsAll filter, so a view holding one would behave differently in the
            # app than via ?view=.
            filters["tagsAll"] = tags

    tags_exclude_param = params.get("tags_exclude")
    if tags_exclude_param:
        tags = _decode_json_tag_list(tags_exclude_param)
        if tags:
            filters["tagsExclude"] = tags

    search = params.get("search")
    if search and len(search) <= MAX_SEARCH_LENGTH:
        filters["search"] = search

    date_from = params.get("date_from")
    if date_from:
        # 'all' passes through so an explicit param can disable a view's saved lower bound.
        filters["dateFrom"] = date_from

    date_to = params.get("date_to")
    if date_to:
        filters["dateTo"] = date_to

    order_by = params.get("order_by")
    if order_by:
        sorting = _order_by_to_sorting(order_by)
        if sorting:
            filters["sorting"] = sorting

    return filters


def _sorting_to_order_expressions(sorting: Mapping[str, Any] | None) -> tuple[OrderBy | str, str]:
    column, descending = "updated_at", True
    if sorting and sorting.get("columnKey") in ALLOWED_ORDER_COLUMNS:
        column = sorting["columnKey"]
        descending = sorting.get("order") != 1

    primary: OrderBy | str
    if column in ("sla_due_at", "snoozed_until"):
        # A ticket with no SLA (or no snooze) sorts to the bottom either direction — an
        # absent deadline isn't more urgent than a real one, and it keeps the large NULL
        # block off the first pages so the SLA-sorted rows are what the user actually sees.
        primary = F(column).desc(nulls_last=True) if descending else F(column).asc(nulls_last=True)
    else:
        primary = f"-{column}" if descending else column

    # ticket_number is unique per team (the queryset is already team-scoped), so it breaks
    # ties deterministically. Without it, rows equal on the primary key — every no-SLA
    # ticket shares NULL sla_due_at — have no stable order across the separate LIMIT/OFFSET
    # page queries, so pages overlap or drop rows and the sort looks lost past page 1.
    return primary, "-ticket_number"


def _assignee_filter_q(entries: list[Any], user: User | None) -> Q:
    user_ids: list[int] = []
    role_ids: list[uuid.UUID] = []
    include_unassigned = False
    for entry in entries:
        if entry == "unassigned":
            include_unassigned = True
        elif entry == "me":
            # Dynamic per-viewer token: resolve to the requesting user so a
            # shared saved view scoped to "me" means each viewer's own tickets.
            if user is not None:
                user_ids.append(user.id)
        elif isinstance(entry, dict) and entry.get("type") == "user":
            try:
                user_ids.append(int(entry["id"]))
            except (ValueError, TypeError):
                pass
        elif isinstance(entry, dict) and entry.get("type") == "role":
            try:
                role_ids.append(uuid.UUID(str(entry["id"])))
            except (ValueError, AttributeError):
                pass
    assignee_q = Q()
    if user_ids:
        assignee_q |= Q(assignment__user_id__in=user_ids)
    if role_ids:
        assignee_q |= Q(assignment__role_id__in=role_ids)
    if include_unassigned:
        assignee_q |= Q(assignment__isnull=True)
    return assignee_q


def is_ticket_number_search(search: str) -> bool:
    # A leading "#" is how ticket numbers are shown in the UI (e.g. "#1234"), so
    # treat "#1234" the same as "1234" and match the ticket number exactly.
    # Restrict to ASCII digits: str.isdigit() also accepts characters like "²"
    # that int() then rejects, which would 500 the request.
    ticket_number_search = search.removeprefix("#")
    return ticket_number_search.isascii() and ticket_number_search.isdigit()


def _apply_search(queryset: QuerySet, search: str, team: Team) -> QuerySet:
    if is_ticket_number_search(search):
        return queryset.filter(ticket_number=int(search.removeprefix("#")))

    # Comment match as a non-correlated subquery: self-contained, so Postgres hashes
    # it once per query (scanning posthog_comment through its trigram index) instead
    # of probing comments per ticket the way a correlated EXISTS would. The ticket id
    # is cast to text rather than item_id to uuid — the id side is always a valid
    # UUID, while a malformed item_id row would make the whole search error.
    comment_match = Comment.objects.filter(
        team_id=team.id,
        scope="conversations_ticket",
        deleted=False,
        content__icontains=search,
    ).values("item_id")

    return queryset.alias(id_text=Cast("id", output_field=CharField())).filter(
        Q(anonymous_traits__name__icontains=search)
        | Q(anonymous_traits__email__icontains=search)
        | Q(email_subject__icontains=search)
        | Q(id_text__in=comment_match)
    )


def apply_ticket_filters(queryset: QuerySet, filters: Mapping[str, Any], *, team: Team, user: User | None) -> QuerySet:
    """Apply a canonical TicketViewFilters mapping to a Ticket queryset and order it.

    `filters` must already be validated/normalized, either by TicketViewFiltersSerializer
    (saved-view path) or by query_params_to_view_filters (flat-param path).
    """
    statuses = filters.get("status") or []
    if statuses:
        queryset = queryset.filter(status__in=statuses)

    priorities = filters.get("priority") or []
    if priorities:
        queryset = queryset.filter(priority__in=priorities)

    channel = filters.get("channel")
    if channel and channel != "all":
        queryset = queryset.filter(channel_source=channel)

    sla = filters.get("sla")
    if sla and sla != "all":
        now = timezone.now()
        if sla == "breached":
            queryset = queryset.filter(sla_due_at__lt=now)
        elif sla == "at-risk":
            queryset = queryset.filter(sla_due_at__gte=now, sla_due_at__lte=now + timedelta(hours=1))
        elif sla == "on-track":
            queryset = queryset.filter(sla_due_at__gt=now + timedelta(hours=1))

    triage_results = set(filters.get("aiTriageResult") or [])
    if triage_results:
        triage_q = Q()
        normal_results = triage_results - {"in_progress"}
        if normal_results:
            triage_q |= Q(ai_triage__result__in=normal_results)
        if "in_progress" in triage_results:
            triage_q |= Q(ai_triage__status="in_progress")
        queryset = queryset.filter(triage_q)

    assignee_entries = normalize_assignee_filter(filters.get("assignee"))
    if assignee_entries:
        assignee_q = _assignee_filter_q(assignee_entries, user)
        if assignee_q:
            queryset = queryset.filter(assignee_q)

    tags = [str(tag) for tag in filters.get("tags") or []][:MAX_TAG_FILTER_VALUES]
    if tags:
        if filters.get("tagsMatch") == "all":
            # One filter per tag (not __in) so this is AND: the ticket must carry every tag.
            for tag_name in tags:
                queryset = queryset.filter(tagged_items__tag__name=tag_name)
            queryset = queryset.distinct()
        else:
            queryset = queryset.filter(tagged_items__tag__name__in=tags).distinct()

    tags_all = [str(tag) for tag in filters.get("tagsAll") or []][:MAX_TAG_FILTER_VALUES]
    if tags_all:
        for tag_name in tags_all:
            queryset = queryset.filter(tagged_items__tag__name=tag_name)
        queryset = queryset.distinct()

    tags_exclude = [str(tag) for tag in filters.get("tagsExclude") or []][:MAX_TAG_FILTER_VALUES]
    if tags_exclude:
        queryset = queryset.exclude(tagged_items__tag__name__in=tags_exclude)

    date_from = filters.get("dateFrom")
    if date_from and date_from != "all":
        parsed = relative_date_parse(date_from, team.timezone_info)
        if parsed:
            queryset = queryset.filter(updated_at__gte=parsed)

    date_to = filters.get("dateTo")
    if date_to and date_to != "all":
        parsed = relative_date_parse(date_to, team.timezone_info)
        if parsed:
            queryset = queryset.filter(updated_at__lte=parsed)

    search = filters.get("search")
    if search and len(search) <= MAX_SEARCH_LENGTH:
        queryset = _apply_search(queryset, search, team)

    return queryset.order_by(*_sorting_to_order_expressions(filters.get("sorting")))
