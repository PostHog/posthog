from typing import Any, Dict

from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.user import UserSerializer
from posthog.email import is_email_available
from posthog.models import OrganizationInvite, OrganizationMembership
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions
from posthog.tasks.email import send_invite


class OrganizationInviteSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(many=False, read_only=True)

    class Meta:
        model = OrganizationInvite
        fields = [
            "id",
            "target_email",
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
        extra_kwargs = {"target_email": {"required": True}}

    def create(self, validated_data: Dict[str, Any], *args: Any, **kwargs: Any) -> OrganizationInvite:
        if OrganizationMembership.objects.filter(
            organization_id=self.context["organization_id"], user__email=validated_data["target_email"]
        ).exists():
            raise exceptions.ValidationError("A user with this email address already belongs to the organization.")
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            organization_id=self.context["organization_id"],
            created_by=self.context["request"].user,
            target_email=validated_data["target_email"],
        )
        if is_email_available(with_absolute_urls=True):
            invite.emailing_attempt_made = True
            send_invite.delay(invite_id=invite.id)
            invite.save()
        return invite


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
