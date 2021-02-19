from typing import Any, Dict, List

from django.db import transaction
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.user import UserSerializer
from posthog.email import is_email_available
from posthog.event_usage import report_bulk_invited, report_team_member_invited
from posthog.models import OrganizationInvite, OrganizationMembership
from posthog.models.organization import Organization
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions
from posthog.tasks.email import send_invite


class OrganizationInviteSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(many=False, read_only=True)

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
            "created_at",
            "updated_at",
            "emailing_attempt_made",
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
                self.context["request"].user.distinct_id,
                name_provided=bool(validated_data.get("first_name")),
                current_invite_count=invite.organization.active_invites.count(),
                current_member_count=OrganizationMembership.objects.filter(
                    organization_id=self.context["organization_id"],
                ).count(),
                email_available=is_email_available(),
            )

        return invite


class BulkCreateOrganizationSerializer(serializers.Serializer):
    invites = OrganizationInviteSerializer(many=True)

    def validate_invites(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(data) > 20:
            raise serializers.ValidationError(
                "A maximum of 20 invites can be sent in a single request.", code="max_length",
            )
        return data

    def create(self, validated_data: Dict[str, Any]) -> Dict[str, Any]:
        output = []
        organization = Organization.objects.get(id=self.context["organization_id"])

        with transaction.atomic():
            for invite in validated_data["invites"]:
                self.context["bulk_create"] = True
                serializer = OrganizationInviteSerializer(data=invite, context=self.context)
                serializer.is_valid(raise_exception=False)  # Don't raise, already validated before
                output.append(serializer.save())

        report_bulk_invited(
            self.context["request"].user.distinct_id,
            invitee_count=len(validated_data["invites"]),
            name_count=sum(1 for invite in validated_data["invites"] if invite["first_name"]),
            current_invite_count=organization.active_invites.count(),
            current_member_count=organization.memberships.count(),
            email_available=is_email_available(),
        )

        return {"invites": output}


class OrganizationInviteViewSet(
    StructuredViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrganizationInviteSerializer
    permission_classes = [IsAuthenticated, OrganizationMemberPermissions, OrganizationAdminWritePermissions]
    queryset = OrganizationInvite.objects.all()
    lookup_field = "id"
    ordering = "-created_at"

    def get_queryset(self):
        return (
            self.filter_queryset_by_parents_lookups(super().get_queryset())
            .select_related("created_by")
            .order_by(self.ordering)
        )

    def get_serializer_context(self):
        """
        Extra context provided to the serializer class.
        """
        parents_query_dict = self.get_parents_query_dict()
        return {
            **super().get_serializer_context(),
            "organization_id": (
                self.request.user.organization.id
                if parents_query_dict["organization_id"] == "@current"
                else parents_query_dict["organization_id"]
            ),
        }


class OrganizationInviteBulkViewSet(StructuredViewSetMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = BulkCreateOrganizationSerializer
    permission_classes = (
        IsAuthenticated,
        OrganizationMemberPermissions,
        OrganizationAdminWritePermissions,
    )
