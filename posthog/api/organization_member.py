from django.db.models import QuerySet, query
from django.http.response import Http404
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, mixins, response, serializers, status, viewsets

from posthog.models import OrganizationMembership
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions


class OrganizationMembershipSerializer(serializers.ModelSerializer):
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    membership_id = serializers.CharField(source="id", read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = ["membership_id", "user_id", "user_first_name", "user_email", "level", "joined_at", "updated_at"]


class OrganizationMemberViewSet(
    mixins.DestroyModelMixin, mixins.UpdateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    serializer_class = OrganizationMembershipSerializer
    pagination_class = None
    permission_classes = [OrganizationMemberPermissions, OrganizationAdminWritePermissions]
    queryset = OrganizationMembership.objects.none()
    lookup_field = "user_id"
    ordering_fields = ["level", "joined_at", "user_first_name"]
    ordering = ["level", "-joined_at"]

    def filter_queryset_by_parents_lookups(self, queryset) -> QuerySet:
        parents_query_dict = self.get_parents_query_dict()
        print(parents_query_dict)
        if parents_query_dict:
            try:
                return queryset.filter(**parents_query_dict)
            except ValueError:
                raise Http404
        else:
            return queryset

        organization_id = self.kwargs["organization_pk"]
        if organization_id == "@current":
            organization_id = self.request.user.organization.id
        return (
            OrganizationMembership.objects.filter(organization_id=organization_id)
            .select_related("user")
            .order_by("-joined_at")
        )

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return queryset.get(user=self.request.user)
        filter_kwargs = {self.lookup_field: lookup_value}
        obj = get_object_or_404()(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def destroy(self, request, *args, **kwargs):
        """Member removal with validation (admin permissions)."""
        member_to_delete = self.get_object()
        try:
            if (
                member_to_delete != request.user
                and request.user.organization_memberships.get(organization=request.user.organization).level
                < OrganizationMembership.Level.ADMIN
            ):
                raise exceptions.PermissionDenied("You are not permitted to delete other organization members.")
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound("User does not exist or does not belong to the organization.")
        OrganizationMembership.objects.get(organization=request.user.organization, user=member_to_delete)
        return response.Response(status=status.HTTP_204_NO_CONTENT)
