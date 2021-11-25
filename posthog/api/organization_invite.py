from typing import Any, Dict, cast

from rest_framework import exceptions, mixins, request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.email import is_email_available
from posthog.event_usage import report_bulk_invited, report_team_member_invited
from posthog.models import OrganizationInvite, OrganizationMembership
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.permissions import OrganizationMemberPermissions
from posthog.tasks.email import send_invite


class OrganizationInviteSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = OrganizationInvite
        fields = [
            "id",
            "target_email",
            "first_name",
            "emailing_attempt_made",
            "is_expired",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "emailing_attempt_made",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"target_email": {"required": True, "allow_null": False}}

    def create(self, validated_data: Dict[str, Any], *args: Any, **kwargs: Any) -> OrganizationInvite:
        if OrganizationMembership.objects.filter(
            organization_id=self.context["organization_id"], user__email=validated_data["target_email"]
        ).exists():
            raise exceptions.ValidationError("A user with this email address already belongs to the organization.")
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            organization_id=self.context["organization_id"], created_by=self.context["request"].user, **validated_data,
        )

        if is_email_available(with_absolute_urls=True):
            invite.emailing_attempt_made = True
            send_invite.delay(invite_id=invite.id)
            invite.save()

        if not self.context.get("bulk_create"):
            report_team_member_invited(
                self.context["request"].user,
                name_provided=bool(validated_data.get("first_name")),
                current_invite_count=invite.organization.active_invites.count(),
                current_member_count=OrganizationMembership.objects.filter(
                    organization_id=self.context["organization_id"],
                ).count(),
                email_available=is_email_available(),
            )

        return invite


class OrganizationInviteViewSet(
    StructuredViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrganizationInviteSerializer
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions]
    queryset = OrganizationInvite.objects.all()
    lookup_field = "id"
    ordering = "-created_at"

    def get_queryset(self):
        return (
            self.filter_queryset_by_parents_lookups(super().get_queryset())
            .select_related("created_by")
            .order_by(self.ordering)
        )

    @action(methods=["POST"], detail=False)
    def bulk(self, request: request.Request, **kwargs) -> response.Response:
        data = cast(Any, request.data)
        if not isinstance(data, list):
            raise exceptions.ValidationError("This endpoint needs an array of data for bulk invite creation.")
        if len(data) > 20:
            raise exceptions.ValidationError(
                "A maximum of 20 invites can be sent in a single request.", code="max_length",
            )

        serializer = OrganizationInviteSerializer(
            data=data, many=True, context={**self.get_serializer_context(), "bulk_create": True}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        organization = Organization.objects.get(id=self.organization_id)
        report_bulk_invited(
            cast(User, self.request.user),
            invitee_count=len(serializer.validated_data),
            name_count=sum(1 for invite in serializer.validated_data if invite.get("first_name")),
            current_invite_count=organization.active_invites.count(),
            current_member_count=organization.memberships.count(),
            email_available=is_email_available(),
        )

        return response.Response(serializer.data, status=status.HTTP_201_CREATED)
