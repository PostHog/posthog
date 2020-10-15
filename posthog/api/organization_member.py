from django.db.models import Model, QuerySet, query
from django.http.response import Http404
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, mixins, response, serializers, status, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework_extensions.mixins import NestedViewSetMixin

from posthog.models import OrganizationMembership
from posthog.permissions import OrganizationAdminWritePermissions, OrganizationMemberPermissions, extract_organization


class OrganizationAdminWriteExcludingDeletePermissions(BasePermission):
    """Require organization admin level to change object, allowing everyone read AND delete."""

    message = "Your organization access level is insufficient."

    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        if request.method in SAFE_METHODS or request.method == "DELETE":
            return True
        organization = extract_organization(object)
        return (
            OrganizationMembership.objects.get(user=request.user, organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )


class OrganizationMembershipSerializer(serializers.ModelSerializer):
    user_first_name = serializers.CharField(source="user.first_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    membership_id = serializers.CharField(source="id", read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = ["membership_id", "user_id", "user_first_name", "user_email", "level", "joined_at", "updated_at"]


class OrganizationMemberViewSet(
    NestedViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OrganizationMembershipSerializer
    pagination_class = None
    permission_classes = [OrganizationMemberPermissions, OrganizationAdminWriteExcludingDeletePermissions]
    queryset = OrganizationMembership.objects.all()
    lookup_field = "user_id"
    ordering_fields = ["level", "joined_at", "user_first_name"]
    ordering = ["level", "-joined_at"]

    def filter_queryset_by_parents_lookups(self, queryset) -> QuerySet:
        parents_query_dict = self.get_parents_query_dict()
        if parents_query_dict:
            if parents_query_dict["organization_id"] == "@current":
                parents_query_dict["organization_id"] = self.request.user.organization.id
            try:
                return queryset.filter(**parents_query_dict)
            except ValueError:
                raise Http404
        else:
            return queryset

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return queryset.get(user=self.request.user)
        filter_kwargs = {self.lookup_field: lookup_value}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def destroy(self, request, *args, **kwargs):
        """Member removal with validation (admin permissions)."""
        membership_to_delete = self.get_object()
        try:
            if (
                membership_to_delete.user != request.user
                and request.user.organization_memberships.get(organization=request.user.organization).level
                < OrganizationMembership.Level.ADMIN
            ):
                raise exceptions.PermissionDenied("You are not permitted to delete other organization members.")
        except OrganizationMembership.DoesNotExist:
            raise exceptions.NotFound("User does not exist or does not belong to the organization.")
        membership_to_delete.delete()
        return response.Response(status=status.HTTP_204_NO_CONTENT)
