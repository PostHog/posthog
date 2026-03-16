from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import timedelta

from django.db import transaction
from django.db.models import Prefetch, Q, QuerySet, Sum
from django.http import Http404
from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from loginas.utils import is_impersonated_session
from openai import APITimeoutError, RateLimitError
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
from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.person.person import READ_DB_FOR_PERSONS, Person, PersonDistinctId
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
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
from products.conversations.backend.models import Ticket, TicketAssignment
from products.conversations.backend.models.constants import Channel, Priority, Status
from products.conversations.backend.services.ai_suggest import NoMessagesError, suggest_reply

from ee.models.rbac.role import Role

logger = structlog.get_logger(__name__)


class SuggestReplyResponseSerializer(serializers.Serializer):
    suggestion = serializers.CharField()


class SuggestReplyErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    error_type = serializers.CharField(required=False)


class TicketPagination(pagination.LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


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

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_number",
            "channel_source",
            "distinct_id",
            "status",
            "priority",
            "assignee",
            "anonymous_traits",
            "ai_resolved",
            "escalation_reason",
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
            "slack_channel_id",
            "slack_thread_ts",
            "slack_team_id",
            "person",
            "tags",
        ]
        read_only_fields = [
            "id",
            "ticket_number",
            "channel_source",
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
            "person",
        ]


class TicketViewSet(TaggedItemViewSetMixin, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "ticket"
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    pagination_class = TicketPagination
    posthog_feature_flag = {
        "product-support-ai-suggestion": ["suggest_reply"],
    }

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        """Filter tickets by team."""
        queryset = queryset.filter(team_id=self.team_id)
        queryset = queryset.select_related("assignment", "assignment__user", "assignment__role")

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
                role_id = assignee[5:]
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

        search = self.request.query_params.get("search")
        if search and len(search) <= 200:
            if search.isdigit():
                queryset = queryset.filter(ticket_number=int(search))
            else:
                queryset = queryset.filter(
                    Q(anonymous_traits__name__icontains=search) | Q(anonymous_traits__email__icontains=search)
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

        tags_param = self.request.query_params.get("tags")
        if tags_param:
            try:
                tags_list = json.loads(tags_param)
                if isinstance(tags_list, list) and tags_list:
                    queryset = queryset.filter(tagged_items__tag__name__in=tags_list).distinct()
            except json.JSONDecodeError:
                pass

        allowed_orderings = {"updated_at", "-updated_at", "sla_due_at", "-sla_due_at", "created_at", "-created_at"}
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

        # Query PersonDistinctId to get Person objects in a single batch
        person_distinct_ids = (
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(distinct_id__in=distinct_ids, team_id=self.team_id)
            .prefetch_related(
                Prefetch(
                    "person",
                    queryset=Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team_id=self.team_id),
                )
            )
        )

        # Build distinct_id -> person mapping
        distinct_id_to_person: dict[str, Person] = {}
        person_ids: set[int] = set()
        for pdi in person_distinct_ids:
            if pdi.person:
                distinct_id_to_person[pdi.distinct_id] = pdi.person
                person_ids.add(pdi.person.id)

        # Batch-load all distinct_ids for all persons
        if person_ids:
            all_pdis = PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS).filter(
                person_id__in=person_ids, team_id=self.team_id
            )
            person_to_distinct_ids: dict[int, list[str]] = {}
            for pdi in all_pdis:
                person_to_distinct_ids.setdefault(pdi.person_id, []).append(pdi.distinct_id)

            for person in distinct_id_to_person.values():
                person._distinct_ids = person_to_distinct_ids.get(person.id, [])

        # Attach person to each ticket (dynamic attribute for serialization)
        for ticket in tickets:
            if ticket.distinct_id:
                ticket.person = distinct_id_to_person.get(ticket.distinct_id)

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

        # Extract assignee without mutating request.data
        assignee = request.data.get("assignee", ...) if "assignee" in request.data else ...
        data = {k: v for k, v in request.data.items() if k != "assignee"}

        # Update other fields normally
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        # Handle assignee update if provided (not ... sentinel)
        if assignee is not ...:
            assign_ticket(
                instance,
                assignee,
                self.organization,
                request.user,
                self.team_id,
                is_impersonated_session(request),
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
                capture_ticket_status_changed(instance, old_status, new_status)

            if priority_changed:
                capture_ticket_priority_changed(instance, old_priority, new_priority)
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

        if changes:
            try:
                log_activity(
                    organization_id=self.organization.id,
                    team_id=self.team_id,
                    user=request.user,
                    was_impersonated=is_impersonated_session(request),
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
        if status_changed or priority_changed or assignee_changed or sla_changed:
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

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(response=SuggestReplyResponseSerializer),
            400: OpenApiResponse(response=SuggestReplyErrorSerializer),
            403: OpenApiResponse(response=SuggestReplyErrorSerializer),
            500: OpenApiResponse(response=SuggestReplyErrorSerializer),
        },
    )
    @action(
        detail=True,
        methods=["POST"],
        url_path="suggest_reply",
        throttle_classes=[AIBurstRateThrottle, AISustainedRateThrottle],
    )
    def suggest_reply_action(self, request, *args, **kwargs):
        if not self.organization.is_ai_data_processing_approved:
            return Response(
                {"detail": "AI data processing is not approved for this organization"},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        ticket = self.get_object()

        try:
            reply_text = suggest_reply(ticket, self.team, request.user.distinct_id)
            return Response({"suggestion": reply_text})
        except NoMessagesError:
            return Response(
                {"detail": "No messages in this ticket"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        except ValueError:
            logger.warning("AI suggest_reply validation error", extra={"ticket_id": str(ticket.id)})
            return Response(
                {
                    "detail": "Failed to generate suggestion. Please try again.",
                    "error_type": "validation_error",
                },
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            # Check for specific error types
            error_type = "unknown_error"
            error_msg = "Failed to generate suggestion"

            if isinstance(e, APITimeoutError):
                error_type = "timeout"
                error_msg = "AI service timed out. Please try again."
            elif isinstance(e, RateLimitError):
                error_type = "rate_limit"
                error_msg = "AI service rate limit reached. Please try again in a moment."
            else:
                error_msg = "Failed to generate suggestion. Please try again."

            logger.exception(
                "AI suggest_reply failed", extra={"ticket_id": str(ticket.id), "error_type": type(e).__name__}
            )
            capture_exception(e, {"ticket_id": str(ticket.id)})
            return Response(
                {"detail": error_msg, "error_type": error_type},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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


def assign_ticket(ticket: Ticket, assignee, organization, user, team_id, was_impersonated):
    """
    Assign a ticket to a user or role.

    Args:
        ticket: The ticket to assign
        assignee: Dict with 'type' ('user' or 'role') and 'id', or None to unassign
        organization: The organization
        user: The user making the change
        team_id: The team ID
        was_impersonated: Whether the session is impersonated
    """
    validate_assignee(assignee)
    validate_assignee_membership(assignee, organization)

    with transaction.atomic():
        # Lock the ticket to prevent concurrent modifications
        Ticket.objects.select_for_update().get(id=ticket.id)
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
            capture_ticket_assigned(ticket, assignee_type, assignee_id)
        except Exception as e:
            capture_exception(e, {"ticket_id": str(ticket.id)})
