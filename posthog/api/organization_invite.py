from typing import Any, Dict

from django.db.models import QuerySet
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework_extensions.mixins import NestedViewSetMixin

from posthog.api.routing import StructuredViewSetMixin
from posthog.email import is_email_available
from posthog.models import OrganizationInvite, OrganizationMembership
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions
from posthog.tasks.email import send_invite


class OrganizationInviteSerializer(serializers.ModelSerializer):
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    created_by_email = serializers.CharField(source="created_by.email", read_only=True)
    created_by_first_name = serializers.CharField(source="created_by.first_name", read_only=True)
    is_expired = serializers.SerializerMethodField()
    # Listing target_email explicitly here as it's nullable in ORM but actually required
    target_email = serializers.CharField(required=True)

    class Meta:
        model = OrganizationInvite
        fields = [
            "id",
            "target_email",
            "created_by_id",
            "created_by_email",
            "created_by_first_name",
            "created_at",
            "updated_at",
            "emailing_attempt_made",
            "is_expired",
        ]
        read_only_fields = [
            "id",
            "created_by_id",
            "created_by_email",
            "created_by_first_name",
            "created_at",
            "updated_at",
            "emailing_attempt_made",
            "is_expired",
        ]

    def get_is_expired(self, invite: OrganizationInvite) -> bool:
        return invite.is_expired()

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
