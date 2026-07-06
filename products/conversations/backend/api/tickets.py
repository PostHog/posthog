from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import timedelta

from django.db import transaction
from django.db.models import CharField, Exists, OuterRef, Q, QuerySet, Sum
from django.db.models.functions import Cast
from django.http import Http404
from django.utils import timezone

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import (
    pagination,
    serializers,
    status as drf_status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.person import get_person_name
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import Change, Detail, Trigger, log_activity
from posthog.models.comment import Comment
from posthog.models.person.person import Person
from posthog.models.person.util import get_person_by_distinct_id, get_persons_by_distinct_ids
from posthog.permissions import APIScopePermission
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.rate_limit import ComposeTicketBurstThrottle, ComposeTicketSustainedThrottle
from posthog.utils import relative_date_parse

from products.conversations.backend.api.serializers import TicketAssignmentSerializer
from products.conversations.backend.cache import (
    get_cached_unread_count,
    invalidate_unread_count_cache,
    set_cached_unread_count,
)
from products.conversations.backend.events import (
    capture_ticket_assigned,
    capture_ticket_priority_changed,
    capture_ticket_status_changed,
)
from products.conversations.backend.models import EmailChannel, Ticket, TicketAssignment
from products.conversations.backend.models.constants import Channel, ChannelDetail, Priority, Status
from products.conversations.backend.person_lookup import _get_persons_by_email

from ee.models.rbac.role import Role

logger = structlog.get_logger(__name__)


class TicketErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    error_type = serializers.CharField(required=False)


class TicketMessageSerializer(serializers.Serializer):
    """A single message in a ticket thread (output-only)."""

    id = serializers.UUIDField(read_only=True, help_text="Message (comment) UUID.")
    content = serializers.CharField(read_only=True, help_text="Plain-text message body.")
    rich_content = serializers.JSONField(read_only=True, allow_null=True, help_text="TipTap rich content JSON, if any.")
    author_type = serializers.CharField(read_only=True, help_text="One of: customer, support, AI.")
    author_name = serializers.CharField(read_only=True, help_text="Display name of the author.")
    is_private = serializers.BooleanField(
        read_only=True, help_text="True for internal notes not visible to the customer."
    )
    created_at = serializers.DateTimeField(read_only=True)


class TicketReplyRequestSerializer(serializers.Serializer):
    """Payload for posting a reply or internal note to a ticket."""

    message = serializers.CharField(
        max_length=5000,
        help_text="Reply content in markdown.",
    )
    is_private = serializers.BooleanField(
        default=False,
        help_text=(
            "If true, store as an internal note (not sent to the customer). "
            "If false, the reply is delivered to the customer over the ticket's channel."
        ),
    )
    rich_content = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Optional TipTap rich content JSON for formatted messages.",
    )

    def validate_message(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Message content is required.")
        return value.strip()

    def validate_rich_content(self, value: object) -> object:
        if value is None:
            return value
        try:
            serialized = json.dumps(value)
        except (TypeError, ValueError) as e:
            raise serializers.ValidationError("Rich content must be JSON-serializable.") from e
        if len(serialized) > 100_000:
            raise serializers.ValidationError("Rich content too large (max 100KB).")
        return value


class ComposeTicketSerializer(serializers.Serializer):
    recipient_email = serializers.EmailField(
        help_text="Recipient email address.",
    )
    recipient_distinct_id = serializers.CharField(
        required=False,
        max_length=400,
        help_text="PostHog distinct_id to link the ticket to a person. Falls back to recipient_email.",
    )
    email_subject = serializers.CharField(
        required=False,
        max_length=500,
        help_text="Email subject line.",
    )
    email_config_id = serializers.UUIDField(
        help_text="ID of the EmailChannel to send from.",
    )
    message = serializers.CharField(
        max_length=5000,
        help_text="Message content in markdown.",
    )
    rich_content = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="TipTap rich content JSON for formatted messages.",
    )

    def validate_message(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Message content is required.")
        return value.strip()

    def validate_rich_content(self, value: object) -> object:
        if value is None:
            return value
        try:
            serialized = json.dumps(value)
        except (TypeError, ValueError) as e:
            raise serializers.ValidationError("Rich content must be JSON-serializable.") from e
        if len(serialized) > 100_000:
            raise serializers.ValidationError("Rich content too large (max 100KB).")
        return value


class ComposeTicketResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Created ticket UUID.")
    ticket_number = serializers.IntegerField(help_text="Human-readable ticket number.")


BULK_UPDATE_STATUS_MAX_IDS = 500


class BulkUpdateStatusRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=BULK_UPDATE_STATUS_MAX_IDS,
        help_text="List of ticket UUIDs to update.",
    )
    status = serializers.ChoiceField(
        choices=Status.choices,
        help_text="New status to apply to all selected tickets: new, open, pending, on_hold, or resolved.",
    )


class BulkUpdateStatusResponseSerializer(serializers.Serializer):
    updated = serializers.IntegerField(help_text="Number of tickets whose status actually changed.")
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="UUIDs of the tickets whose status changed.",
    )


class TicketPagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


class TicketMessagePagination(pagination.LimitOffsetPagination):
    default_limit = 50
    max_limit = 200


MAX_TAG_FILTER_VALUES = 50


class TicketPersonSerializer(serializers.Serializer):
    """Minimal person serializer for embedding in ticket responses."""

    id = serializers.UUIDField(source="uuid", read_only=True)
    name = serializers.SerializerMethodField()
    distinct_ids = serializers.ListField(child=serializers.CharField(), read_only=True)
    properties = serializers.DictField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    is_identified = serializers.BooleanField(read_only=True)

    def get_name(self, person: Person) -> str:
        team = self.context.get("team")
        if team is None:
            return ""
        return get_person_name(team, person)


class TicketSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    assignee = TicketAssignmentSerializer(source="assignment", read_only=True)
    person = TicketPersonSerializer(read_only=True, allow_null=True)
    email_to = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_number",
            "channel_source",
            "channel_detail",
            "distinct_id",
            "status",
            "priority",
            "assignee",
            "anonymous_traits",
            "identity_verified",
            "ai_resolved",
            "escalation_reason",
            "ai_triage",
            "created_at",
            "updated_at",
            "message_count",
            "last_message_at",
            "last_message_text",
            "unread_team_count",
            "unread_customer_count",
            "session_id",
            "session_context",
            "sla_due_at",
            "snoozed_until",
            "slack_channel_id",
            "slack_thread_ts",
            "slack_team_id",
            "email_subject",
            "email_from",
            "email_to",
            "cc_participants",
            "github_repo",
            "github_issue_number",
            "organization_id",
            "person",
            "tags",
        ]
        read_only_fields = [
            "id",
            "ticket_number",
            "channel_source",
            "channel_detail",
            "distinct_id",
            "created_at",
            "message_count",
            "last_message_at",
            "last_message_text",
            "unread_team_count",
            "unread_customer_count",
            "assignee",
            "session_id",
            "session_context",
            "slack_channel_id",
            "slack_thread_ts",
            "slack_team_id",
            "email_subject",
            "email_from",
            "email_to",
            "cc_participants",
            "github_repo",
            "github_issue_number",
            "organization_id",
            "person",
            "ai_triage",
            "identity_verified",
        ]
        extra_kwargs = {
            "identity_verified": {
                "help_text": (
                    "Trust signal indicating whether the ticket's claimed identity was attested by the server "
                    "(widget HMAC, SPF-authenticated email, or a signature-validated platform webhook). "
                    "True when verified, false when assessed but not attested, null when unknown "
                    "(e.g. created before this signal existed)."
                )
            },
            "status": {"help_text": "Ticket status: new, open, pending, on_hold, or resolved"},
            "priority": {"help_text": "Ticket priority: low, medium, or high. Null if unset."},
            "sla_due_at": {"help_text": "SLA deadline set via workflows. Null means no SLA."},
            "anonymous_traits": {"help_text": "Customer-provided traits such as name and email"},
            "organization_id": {
                "help_text": "Customer's PostHog organization group key, resolved at ticket creation. Null when unknown."
            },
            "ai_triage": {
                "help_text": "AI support pipeline triage and outcome (status, result, ticket_type, confidence, attempts, etc.)."
            },
        }

    def get_email_to(self, obj: Ticket) -> str | None:
        config = getattr(obj, "email_config", None)
        if config is not None:
            return config.from_email
        return None


TICKET_ID_PARAM = OpenApiParameter(
    name="id",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    description="The ticket's UUID or its numeric ticket number.",
)


@extend_schema_view(
    retrieve=extend_schema(parameters=[TICKET_ID_PARAM]),
    update=extend_schema(parameters=[TICKET_ID_PARAM]),
    partial_update=extend_schema(parameters=[TICKET_ID_PARAM]),
    destroy=extend_schema(parameters=[TICKET_ID_PARAM]),
)
class TicketViewSet(TaggedItemViewSetMixin, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "ticket"
    scope_object_read_actions = ["list", "retrieve", "unread_count", "messages"]
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "compose", "reply"]
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    pagination_class = TicketPagination

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        """Filter tickets by team."""
        queryset = queryset.filter(team_id=self.team_id)
        queryset = queryset.select_related("assignment", "assignment__user", "assignment__role", "email_config")

        status_param = self.request.query_params.get("status")
        if status_param:
            valid_statuses = [s.value for s in Status]
            statuses = [s.strip() for s in status_param.split(",") if s.strip() in valid_statuses]
            if len(statuses) == 1:
                queryset = queryset.filter(status=statuses[0])
            elif len(statuses) > 1:
                queryset = queryset.filter(status__in=statuses)

        priority_param = self.request.query_params.get("priority")
        if priority_param:
            valid_priorities = [p.value for p in Priority]
            priorities = [p.strip() for p in priority_param.split(",") if p.strip() in valid_priorities]
            if len(priorities) == 1:
                queryset = queryset.filter(priority=priorities[0])
            elif len(priorities) > 1:
                queryset = queryset.filter(priority__in=priorities)

        channel_source = self.request.query_params.get("channel_source")
        if channel_source and channel_source in [c.value for c in Channel]:
            queryset = queryset.filter(channel_source=channel_source)

        channel_detail = self.request.query_params.get("channel_detail")
        if channel_detail and channel_detail in [d.value for d in ChannelDetail]:
            queryset = queryset.filter(channel_detail=channel_detail)

        assignee = self.request.query_params.get("assignee")
        if assignee:
            if assignee.lower() == "unassigned":
                queryset = queryset.filter(assignment__isnull=True)
            elif assignee.startswith("user:"):
                try:
                    user_id = int(assignee[5:])
                    queryset = queryset.filter(assignment__user_id=user_id)
                except ValueError:
                    pass
            elif assignee.startswith("role:"):
                try:
                    role_id = uuid.UUID(assignee[5:])
                except (ValueError, AttributeError):
                    pass
                else:
                    queryset = queryset.filter(assignment__role_id=role_id)

        date_from = self.request.query_params.get("date_from")
        if date_from and date_from != "all":
            parsed = relative_date_parse(date_from, self.team.timezone_info)
            if parsed:
                queryset = queryset.filter(updated_at__gte=parsed)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            parsed = relative_date_parse(date_to, self.team.timezone_info)
            if parsed:
                queryset = queryset.filter(updated_at__lte=parsed)

        distinct_ids_param = self.request.query_params.get("distinct_ids")
        if distinct_ids_param:
            ids = [id.strip() for id in distinct_ids_param.split(",") if id.strip()][:100]
            if ids:
                queryset = queryset.filter(distinct_id__in=ids)

        # By-id reads without retrieve's mark-as-read side effect (e.g. a client
        # refreshing a set of watched tickets nobody is actively viewing).
        ids_param = self.request.query_params.get("ids")
        if ids_param:
            ticket_ids = []
            for raw in ids_param.split(",")[:100]:
                try:
                    ticket_ids.append(uuid.UUID(raw.strip()))
                except ValueError:
                    continue
            if ticket_ids:
                queryset = queryset.filter(id__in=ticket_ids)

        search = self.request.query_params.get("search")
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

        sla_param = self.request.query_params.get("sla")
        if sla_param:
            now = timezone.now()
            if sla_param == "breached":
                queryset = queryset.filter(sla_due_at__lt=now)
            elif sla_param == "at-risk":
                queryset = queryset.filter(sla_due_at__gte=now, sla_due_at__lte=now + timedelta(hours=1))
            elif sla_param == "on-track":
                queryset = queryset.filter(sla_due_at__gt=now + timedelta(hours=1))

        snoozed_param = self.request.query_params.get("snoozed")
        if snoozed_param is not None:
            if snoozed_param.lower() == "true":
                queryset = queryset.filter(snoozed_until__isnull=False)
            elif snoozed_param.lower() == "false":
                queryset = queryset.filter(snoozed_until__isnull=True)

        tags_param = self.request.query_params.get("tags")
        if tags_param:
            try:
                tags_list = json.loads(tags_param)
                if isinstance(tags_list, list) and tags_list:
                    queryset = queryset.filter(tagged_items__tag__name__in=tags_list[:MAX_TAG_FILTER_VALUES]).distinct()
            except json.JSONDecodeError:
                pass

        tags_all_param = self.request.query_params.get("tags_all")
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

        tags_exclude_param = self.request.query_params.get("tags_exclude")
        if tags_exclude_param:
            try:
                tags_exclude_list = json.loads(tags_exclude_param)
                if isinstance(tags_exclude_list, list) and tags_exclude_list:
                    queryset = queryset.exclude(tagged_items__tag__name__in=tags_exclude_list[:MAX_TAG_FILTER_VALUES])
            except json.JSONDecodeError:
                pass

        ai_triage_result_param = self.request.query_params.get("ai_triage_result")
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

        allowed_orderings = {
            "updated_at",
            "-updated_at",
            "sla_due_at",
            "-sla_due_at",
            "snoozed_until",
            "-snoozed_until",
            "created_at",
            "-created_at",
            "ticket_number",
            "-ticket_number",
        }
        order_by = self.request.query_params.get("order_by", "-updated_at")
        if order_by not in allowed_orderings:
            order_by = "-updated_at"

        return queryset.order_by(order_by)

    def safely_get_object(self, queryset):
        """
        Support looking up tickets by either UUID or ticket_number.
        This allows URLs like /tickets/123/ (ticket_number) alongside /tickets/<uuid>/ for backward compatibility.
        """
        lookup_value: str | None = self.kwargs.get("pk")

        if not lookup_value:
            raise Http404("Ticket not found")

        # Try to parse as UUID first
        try:
            uuid.UUID(lookup_value)
            # It's a valid UUID - look up by id
            try:
                return queryset.get(id=lookup_value)
            except Ticket.DoesNotExist:
                raise Http404("Ticket not found")
        except (ValueError, AttributeError):
            # Not a UUID - try as ticket_number (integer)
            try:
                ticket_num = int(lookup_value)
                try:
                    return queryset.get(ticket_number=ticket_num)
                except Ticket.DoesNotExist:
                    raise Http404("Ticket not found")
            except (ValueError, TypeError):
                # Neither UUID nor integer
                raise Http404("Ticket not found")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["team"] = self.team
        return context

    def _attach_persons_to_tickets(self, tickets: Sequence[Ticket]) -> None:
        """Batch-fetch persons by distinct_id and attach to tickets."""
        distinct_ids = sorted([t.distinct_id for t in tickets if t.distinct_id])
        if not distinct_ids:
            return

        with personhog_caller_tag("conversations/ticket-attach-persons"):
            persons = get_persons_by_distinct_ids(self.team_id, distinct_ids)

        distinct_id_to_person: dict[str, Person] = {}
        distinct_ids_set = set(distinct_ids)
        for person in persons:
            for did in person.distinct_ids:
                if did in distinct_ids_set:
                    distinct_id_to_person[did] = person

        # Attach person to each ticket (dynamic attribute for serialization)
        for ticket in tickets:
            if ticket.distinct_id:
                ticket.person = distinct_id_to_person.get(ticket.distinct_id)

        # Fallback: for email-channel tickets with no person match,
        # try matching on properties.email (handles cases where the
        # person's distinct_id differs from their email address)
        unmatched = [
            t
            for t in tickets
            if t.distinct_id and not getattr(t, "person", None) and t.channel_source == Channel.EMAIL and t.email_from
        ]
        if unmatched:
            emails = [t.email_from for t in unmatched if t.email_from]
            email_to_person = _get_persons_by_email(self.team, emails)
            for ticket in unmatched:
                if ticket.email_from:
                    found = email_to_person.get(ticket.email_from.lower())
                    if found is not None:
                        ticket.person = found

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Filter by status. Accepts a single value or a comma-separated list "
                    "(e.g. `new,open,pending`). Valid values: `new`, `open`, `pending`, `on_hold`, `resolved`."
                ),
            ),
            OpenApiParameter(
                "priority",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Filter by priority. Accepts a single value or a comma-separated list "
                    "(e.g. `medium,high`). Valid values: `low`, `medium`, `high`."
                ),
            ),
            OpenApiParameter(
                "channel_source",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=[c.value for c in Channel],
                description="Filter by the channel the ticket originated from.",
            ),
            OpenApiParameter(
                "channel_detail",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=[d.value for d in ChannelDetail],
                description="Filter by the channel sub-type (e.g. `widget_embedded`, `slack_bot_mention`).",
            ),
            OpenApiParameter(
                "assignee",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Filter by assignee. Use `unassigned` for tickets with no assignee, "
                    "`user:<user_id>` for a specific user, or `role:<role_uuid>` for a role."
                ),
            ),
            OpenApiParameter(
                "date_from",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Only include tickets updated on or after this date. Accepts absolute dates (`2026-01-01`) "
                    "or relative ones (`-7d`, `-1mStart`). Pass `all` to disable the filter."
                ),
            ),
            OpenApiParameter(
                "date_to",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Only include tickets updated on or before this date. Same format as `date_from`.",
            ),
            OpenApiParameter(
                "distinct_ids",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Comma-separated list of person `distinct_id`s to filter by (max 100).",
            ),
            OpenApiParameter(
                "ids",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Comma-separated list of ticket UUIDs to fetch (max 100). Invalid UUIDs are ignored. "
                    "Unlike fetching a single ticket, listing by `ids` does not mark the tickets as read."
                ),
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Free-text search. A numeric value matches a ticket number exactly; otherwise matches "
                    "against the customer's name or email (case-insensitive, partial match)."
                ),
            ),
            OpenApiParameter(
                "sla",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=["breached", "at-risk", "on-track"],
                description=(
                    "Filter by SLA state. `breached` = past `sla_due_at`, `at-risk` = due within the next hour, "
                    "`on-track` = more than an hour remaining."
                ),
            ),
            OpenApiParameter(
                "tags",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='JSON-encoded array of tag names; returns tickets with ANY of them (OR), e.g. `["billing","urgent"]`.',
            ),
            OpenApiParameter(
                "tags_all",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='JSON-encoded array of tag names; returns tickets that have ALL of them (AND), e.g. `["billing","urgent"]`.',
            ),
            OpenApiParameter(
                "tags_exclude",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='JSON-encoded array of tag names; returns tickets that have NONE of them (NOT), e.g. `["escalated"]`.',
            ),
            OpenApiParameter(
                "order_by",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                enum=[
                    "updated_at",
                    "-updated_at",
                    "sla_due_at",
                    "-sla_due_at",
                    "created_at",
                    "-created_at",
                    "ticket_number",
                    "-ticket_number",
                ],
                description="Sort order. Prefix with `-` for descending. Defaults to `-updated_at`.",
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        """List tickets with person data attached."""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            self._attach_persons_to_tickets(page)
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        tickets = list(queryset)
        self._attach_persons_to_tickets(tickets)
        serializer = self.get_serializer(tickets, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """Get single ticket and mark as read by team."""
        instance = self.get_object()
        if instance.unread_team_count > 0:
            instance.unread_team_count = 0
            instance.save(update_fields=["unread_team_count"])
            # Invalidate cache since unread count changed
            invalidate_unread_count_cache(self.team_id)

        # Attach person data
        self._attach_persons_to_tickets([instance])

        # Track internal analytics
        try:
            report_user_action(
                request.user,
                "support ticket viewed",
                {
                    "channel_source": instance.channel_source,
                    "ticket_status": instance.status,
                    "is_assigned": getattr(instance, "assignment", None) is not None,
                },
                team=self.team,
                request=request,
            )
        except Exception as e:
            capture_exception(e, {"ticket_id": str(instance.id)})

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """Handle ticket updates including assignee changes."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        old_status = instance.status
        old_priority = instance.priority
        old_sla_due_at = instance.sla_due_at
        old_snoozed_until = instance.snoozed_until

        # Extract assignee without mutating request.data
        assignee = request.data.get("assignee", ...) if "assignee" in request.data else ...
        data = {k: v for k, v in request.data.items() if k != "assignee"}

        # Update other fields normally
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)

        explicit_status = "status" in data
        with transaction.atomic():
            self.perform_update(serializer)

            # Auto-status on snooze transitions (only when user didn't explicitly set status)
            new_snoozed_until = instance.snoozed_until
            snooze_changed = old_snoozed_until != new_snoozed_until
            if snooze_changed and not explicit_status:
                if old_snoozed_until is None and new_snoozed_until is not None:
                    instance.status = Status.ON_HOLD
                    instance.save(update_fields=["status"])
                elif old_snoozed_until is not None and new_snoozed_until is None:
                    instance.status = Status.OPEN
                    instance.save(update_fields=["status"])

        # Handle assignee update if provided (not ... sentinel)
        if assignee is not ...:
            assign_ticket(
                instance,
                assignee,
                self.organization,
                request.user,
                self.team_id,
                is_impersonated(request),
            )
            # Refresh instance to get updated assignment
            instance.refresh_from_db()

        # Invalidate unread count cache if status changed to/from resolved
        new_status = instance.status
        if old_status != new_status and (old_status == "resolved" or new_status == "resolved"):
            invalidate_unread_count_cache(self.team_id)

        # Emit analytics events for workflow triggers
        new_priority = instance.priority
        new_sla_due_at = instance.sla_due_at
        status_changed = old_status != new_status
        priority_changed = old_priority != new_priority
        sla_changed = old_sla_due_at != new_sla_due_at
        assignee_changed = assignee is not ...

        try:
            if status_changed:
                capture_ticket_status_changed(instance, old_status, new_status, actor=request.user, actor_type="user")

            if priority_changed:
                capture_ticket_priority_changed(
                    instance, old_priority, new_priority, actor=request.user, actor_type="user"
                )
        except Exception as e:
            capture_exception(e, {"ticket_id": str(instance.id)})

        # Log all field changes to activity log
        changes: list[Change] = []
        if status_changed:
            changes.append(
                Change(
                    type="Ticket",
                    field="status",
                    before=old_status,
                    after=new_status,
                    action="changed",
                )
            )
        if priority_changed:
            changes.append(
                Change(
                    type="Ticket",
                    field="priority",
                    before=old_priority,
                    after=new_priority,
                    action="changed",
                )
            )
        if sla_changed:
            changes.append(
                Change(
                    type="Ticket",
                    field="sla_due_at",
                    before=old_sla_due_at.isoformat() if old_sla_due_at else None,
                    after=new_sla_due_at.isoformat() if new_sla_due_at else None,
                    action="changed",
                )
            )
        if snooze_changed:
            changes.append(
                Change(
                    type="Ticket",
                    field="snoozed_until",
                    before=old_snoozed_until.isoformat() if old_snoozed_until else None,
                    after=new_snoozed_until.isoformat() if new_snoozed_until else None,
                    action="changed",
                )
            )

        if changes:
            try:
                log_activity(
                    organization_id=self.organization.id,
                    team_id=self.team_id,
                    user=request.user,
                    was_impersonated=is_impersonated(request),
                    item_id=str(instance.id),
                    scope="Ticket",
                    activity="updated",
                    detail=Detail(
                        name=f"Ticket #{instance.ticket_number}",
                        changes=changes,
                    ),
                )
            except Exception as e:
                capture_exception(e, {"ticket_id": str(instance.id)})

        # Track internal analytics
        if status_changed or priority_changed or assignee_changed or sla_changed or snooze_changed:
            try:
                report_user_action(
                    request.user,
                    "support ticket updated",
                    {
                        "channel_source": instance.channel_source,
                        "ticket_status": instance.status,
                        "is_assigned": getattr(instance, "assignment", None) is not None,
                    },
                    team=self.team,
                    request=request,
                )
            except Exception as e:
                capture_exception(e, {"ticket_id": str(instance.id)})

        # Re-serialize to include updated assignee
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def _emit_status_change_side_effects(self, request, ticket: Ticket, old_status: str, new_status: str) -> None:
        """Emit analytics + activity log for a single ticket status change.

        Called from both ``update()`` and ``bulk_update_status()`` to keep
        event-tracking logic in one place.
        """
        try:
            capture_ticket_status_changed(ticket, old_status, new_status, actor=request.user, actor_type="user")
        except Exception as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})

        try:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team_id,
                user=request.user,
                was_impersonated=is_impersonated(request),
                item_id=str(ticket.id),
                scope="Ticket",
                activity="updated",
                detail=Detail(
                    name=f"Ticket #{ticket.ticket_number}",
                    changes=[
                        Change(
                            type="Ticket",
                            field="status",
                            before=old_status,
                            after=new_status,
                            action="changed",
                        )
                    ],
                ),
            )
        except Exception as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})

    @extend_schema(
        request=BulkUpdateStatusRequestSerializer,
        responses={200: OpenApiResponse(response=BulkUpdateStatusResponseSerializer)},
    )
    @action(detail=False, methods=["POST"])
    def bulk_update_status(self, request, *args, **kwargs):
        """Update the status of multiple tickets in a single request.

        Only tickets belonging to the current team are affected; other-team UUIDs
        are silently ignored.  Tickets already in the requested status are skipped.
        """
        serializer = BulkUpdateStatusRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket_ids: list[uuid.UUID] = serializer.validated_data["ids"]
        new_status: str = serializer.validated_data["status"]

        changed: list[tuple[Ticket, str]] = []
        with transaction.atomic():
            tickets = list(self.get_queryset().filter(id__in=ticket_ids).select_for_update(of=("self",)))
            for ticket in tickets:
                old_status = ticket.status
                if old_status == new_status:
                    continue
                ticket.status = new_status
                ticket.save(update_fields=["status", "updated_at"])
                changed.append((ticket, old_status))

        def _emit_bulk_side_effects() -> None:
            if any(old == "resolved" or new_status == "resolved" for _, old in changed):
                invalidate_unread_count_cache(self.team_id)

            for ticket, old_status in changed:
                self._emit_status_change_side_effects(request, ticket, old_status, new_status)

            if changed:
                try:
                    report_user_action(
                        request.user,
                        "support tickets bulk status updated",
                        {"count": len(changed), "ticket_status": new_status},
                        team=self.team,
                        request=request,
                    )
                except Exception as e:
                    capture_exception(e, {"team_id": self.team_id})

        transaction.on_commit(_emit_bulk_side_effects)

        return Response({"updated": len(changed), "ids": [str(t.id) for t, _ in changed]})

    @action(detail=False, methods=["get"])
    def unread_count(self, request, *args, **kwargs):
        """
        Get total unread ticket count for the team.

        Returns the sum of unread_team_count for all non-resolved tickets.
        Cached in Redis for 30 seconds, invalidated on changes.
        """
        team_id = self.team_id

        # Check if support is enabled
        if not self.team.conversations_enabled:
            return Response({"count": 0})

        # Try cache first
        cached_count = get_cached_unread_count(team_id)
        if cached_count is not None:
            return Response({"count": cached_count})

        # Query database - only non-resolved tickets with unread messages
        result = (
            Ticket.objects.filter(team_id=team_id)
            .exclude(status="resolved")
            .filter(unread_team_count__gt=0)
            .aggregate(total=Sum("unread_team_count"))
        )
        count = result["total"] or 0

        # Cache the result
        set_cached_unread_count(team_id, count)

        return Response({"count": count})

    @extend_schema(
        parameters=[TICKET_ID_PARAM],
        responses={200: TicketMessageSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], pagination_class=TicketMessagePagination)
    def messages(self, request, *args, **kwargs):
        """Return the message thread for a ticket, ordered chronologically (paginated)."""
        ticket = self.get_object()

        comments = (
            Comment.objects.filter(
                team_id=self.team_id,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                deleted=False,
            )
            .select_related("created_by")
            .order_by("created_at")
        )

        page = self.paginate_queryset(comments)
        comments_to_serialize = page if page is not None else list(comments)

        message_list = [self._serialize_message(comment, ticket) for comment in comments_to_serialize]
        data = TicketMessageSerializer(message_list, many=True).data

        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)

    def _serialize_message(self, comment: Comment, ticket: Ticket) -> dict:
        item_context = comment.item_context or {}
        author_type = item_context.get("author_type", "customer")

        if comment.created_by:
            author_name = comment.created_by.first_name or comment.created_by.email
        elif author_type == "customer":
            traits = ticket.anonymous_traits or {}
            author_name = traits.get("name") or traits.get("email") or "Customer"
        elif author_type == "AI":
            author_name = "PostHog Assistant"
        else:
            author_name = "Support"

        return {
            "id": comment.id,
            "content": comment.content,
            "rich_content": comment.rich_content,
            "author_type": author_type,
            "author_name": author_name,
            "is_private": item_context.get("is_private") is True,
            "created_at": comment.created_at,
        }

    @extend_schema(
        parameters=[TICKET_ID_PARAM],
        request=TicketReplyRequestSerializer,
        responses={
            201: OpenApiResponse(response=TicketMessageSerializer),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        pagination_class=None,
        throttle_classes=[ComposeTicketBurstThrottle, ComposeTicketSustainedThrottle],
    )
    def reply(self, request, *args, **kwargs):
        """Post a reply or internal note to a ticket.

        With is_private=false, the reply is delivered to the customer via the
        ticket's channel (email, Slack, Teams, GitHub). With is_private=true,
        the message is stored as an internal note only visible to team members.
        """
        ticket = self.get_object()

        if not self.team.conversations_enabled:
            return Response(
                {"detail": "Conversations is not enabled."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        serializer = TicketReplyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        is_private = data["is_private"]

        comment = Comment.objects.create(
            team=self.team,
            created_by=request.user,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=data["message"],
            rich_content=data.get("rich_content"),
            item_context={"author_type": "support", "is_private": is_private},
        )

        return Response(
            TicketMessageSerializer(self._serialize_message(comment, ticket)).data,
            status=drf_status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=ComposeTicketSerializer,
        responses={
            201: OpenApiResponse(response=ComposeTicketResponseSerializer),
            400: OpenApiResponse(response=TicketErrorSerializer),
        },
    )
    @action(
        detail=False,
        methods=["POST"],
        pagination_class=None,
        throttle_classes=[ComposeTicketBurstThrottle, ComposeTicketSustainedThrottle],
    )
    def compose(self, request, *args, **kwargs):
        """Create a new outbound ticket and send the first message to the customer."""
        serializer = ComposeTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        team = self.team

        if not team.conversations_enabled:
            return Response(
                {"detail": "Conversations is not enabled."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        settings = team.conversations_settings or {}

        if not settings.get("email_enabled"):
            return Response(
                {"detail": "Email channel is not enabled."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        email_config = EmailChannel.objects.filter(
            id=data["email_config_id"],
            team=team,
            domain_verified=True,
        ).first()
        if not email_config:
            return Response(
                {"detail": "Email configuration not found or domain not verified."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        recipient_email = data["recipient_email"]
        distinct_id = data.get("recipient_distinct_id", "") or recipient_email

        person: Person | None = None
        if distinct_id != recipient_email:
            # Only person.properties is read for this lookup, so skip the distinct-id fetch.
            with personhog_caller_tag("conversations/ticket-recipient-lookup"):
                person = get_person_by_distinct_id(team.id, distinct_id, distinct_id_limit=0)

        if person is None:
            person = _get_persons_by_email(team, [recipient_email]).get(recipient_email.lower())
            if person is not None and person.distinct_ids:
                distinct_id = person.distinct_ids[0]

        if data.get("recipient_distinct_id") and person is not None:
            person_email = (person.properties or {}).get("email", "")
            if person_email and person_email.lower() != recipient_email.lower():
                return Response(
                    {"detail": "Recipient email does not match the person's email on file."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():
            ticket = Ticket.objects.create_with_number(
                team=team,
                channel_source=Channel.EMAIL,
                distinct_id=distinct_id,
                status=Status.OPEN,
                widget_session_id=str(uuid.uuid4()),
                email_config=email_config,
                email_from=data["recipient_email"],
                email_subject=data.get("email_subject", ""),
                # The recipient hasn't proven control of this address — a team member just typed it —
                # so leave identity unknown. It's promoted to verified if/when they reply and authenticate.
                identity_verified=None,
            )

            Comment.objects.create(
                team=team,
                created_by=request.user,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=data["message"],
                rich_content=data.get("rich_content"),
                item_context={"author_type": "human", "is_private": False},
            )

        try:
            report_user_action(
                request.user,
                "support ticket composed",
                {"channel_source": Channel.EMAIL},
                team=team,
                request=request,
            )
        except Exception as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})

        return Response(
            {"id": str(ticket.id), "ticket_number": ticket.ticket_number},
            status=drf_status.HTTP_201_CREATED,
        )


def validate_assignee(assignee) -> None:
    """Validate assignee payload structure."""
    if assignee is None:
        return
    if not isinstance(assignee, dict):
        raise serializers.ValidationError({"assignee": "must be an object"})
    if "type" not in assignee or "id" not in assignee:
        raise serializers.ValidationError({"assignee": "must have 'type' and 'id'"})
    if assignee["type"] not in ("user", "role"):
        raise serializers.ValidationError({"assignee": "type must be 'user' or 'role'"})

    if assignee["type"] == "user":
        if not isinstance(assignee["id"], int):
            raise serializers.ValidationError({"assignee": "user id must be an integer"})
    elif assignee["type"] == "role":
        try:
            uuid.UUID(str(assignee["id"]))
        except (ValueError, AttributeError):
            raise serializers.ValidationError({"assignee": "role id must be a valid UUID"})


def validate_assignee_membership(assignee, organization) -> None:
    """Validate that the assignee belongs to the organization."""
    if assignee is None:
        return

    if assignee["type"] == "user":
        if not OrganizationMembership.objects.filter(organization=organization, user_id=assignee["id"]).exists():
            raise serializers.ValidationError({"assignee": "user is not a member of this organization"})
    elif assignee["type"] == "role":
        if not Role.objects.filter(id=assignee["id"], organization=organization).exists():
            raise serializers.ValidationError({"assignee": "role does not belong to this organization"})


def assign_ticket(
    ticket: Ticket, assignee, organization, user, team_id, was_impersonated, trigger: Trigger | None = None
):
    """
    Assign a ticket to a user or role.

    Args:
        ticket: The ticket to assign
        assignee: Dict with 'type' ('user' or 'role') and 'id', or None to unassign
        organization: The organization
        user: The user making the change
        team_id: The team ID
        was_impersonated: Whether the session is impersonated
        trigger: Optional Trigger identifying an automated source (e.g. a workflow) that made the change
    """
    validate_assignee(assignee)
    validate_assignee_membership(assignee, organization)

    with transaction.atomic():
        # Lock the ticket to prevent concurrent modifications
        Ticket.objects.select_for_update().get(id=ticket.id, team_id=team_id)
        assignment_before = TicketAssignment.objects.filter(ticket_id=ticket.id).first()
        serialized_assignment_before = TicketAssignmentSerializer(assignment_before).data if assignment_before else None

        if assignee:
            assignment_after, _ = TicketAssignment.objects.update_or_create(
                ticket_id=ticket.id,
                defaults={
                    "user_id": None if assignee["type"] != "user" else assignee["id"],
                    "role_id": None if assignee["type"] != "role" else assignee["id"],
                },
            )
            serialized_assignment_after = TicketAssignmentSerializer(assignment_after).data
        else:
            if assignment_before:
                assignment_before.delete()
            serialized_assignment_after = None

        log_activity(
            organization_id=organization.id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=str(ticket.id),
            scope="Ticket",
            activity="assigned",
            detail=Detail(
                name=f"Ticket #{ticket.ticket_number}",
                changes=[
                    Change(
                        type="Ticket",
                        field="assignee",
                        before=serialized_assignment_before,
                        after=serialized_assignment_after,
                        action="changed",
                    )
                ],
                trigger=trigger,
            ),
        )

        # Emit analytics event for workflow triggers
        try:
            if assignee:
                assignee_type = assignee["type"]
                assignee_id = str(assignee["id"])
            else:
                assignee_type = None
                assignee_id = None
            capture_ticket_assigned(ticket, assignee_type, assignee_id, actor=user, actor_type="user")
        except Exception as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})
