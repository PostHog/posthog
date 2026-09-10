from rest_framework import serializers, viewsets
from rest_framework.permissions import BasePermission


# === SHOULD MATCH (ruleid) ===


# A: request.user.organization in has_permission
class BadPermission(BasePermission):
    def has_permission(self, request, view):
        # ruleid: cross-org-bypass-user-organization
        org = request.user.organization
        return True


# B: self.context["request"].user.organization in serializer
class BadSerializer(serializers.ModelSerializer):
    def validate_name(self, name):
        # ruleid: cross-org-bypass-user-organization
        org = self.context["request"].user.organization
        return name


# C: self.request.user.organization in viewset
class BadViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    def get_org(self):
        # ruleid: cross-org-bypass-user-organization
        return self.request.user.organization


# === SHOULD NOT MATCH (ok) ===


# Safe: get_organization_from_view
class GoodPermission(BasePermission):
    def has_permission(self, request, view):
        # ok: cross-org-bypass-user-organization
        org = get_organization_from_view(view)
        return True


# Safe: self.context["view"].organization
class GoodSerializer(serializers.ModelSerializer):
    def create(self, validated_data):
        # ok: cross-org-bypass-user-organization
        org = self.context["view"].organization
        return super().create(validated_data)


# Safe: self.organization in viewset
class GoodViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    def get_org(self):
        # ok: cross-org-bypass-user-organization
        return self.organization


# Safe: standalone view (not org-nested)
def saml_view(request):
    # ok: cross-org-bypass-user-organization
    org = request.user.organization
    return org


# === KNOWN LIMITATION (todoruleid) ===


# Aliased variable — can't catch without taint mode
class AliasedPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        # todoruleid: cross-org-bypass-user-organization
        org = user.organization
        return True
