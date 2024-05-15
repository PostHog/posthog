from django.conf import settings
from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import ProxyRecord
from posthog.permissions import OrganizationAdminWritePermissions
from rest_framework.response import Response


class ProxyRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyRecord
        fields = (
            "id",
            "domain",
            "target_cname",
            "status",
            "created_at",
            "updated_at",
            "created_by",
        )
        read_only_fields = ("target_cname", "created_at", "created_by", "status")


class ProxyRecordViewset(TeamAndOrgViewSetMixin, ModelViewSet):
    scope_object = "organization"
    serializer_class = ProxyRecordSerializer
    permission_classes = [OrganizationAdminWritePermissions]

    def list(self, request, *args, **kwargs):
        queryset = self.organization.proxy_records.order_by("-created_at")
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        domain = request.data.get("domain")
        queryset = self.organization.proxy_records.order_by("-created_at")
        queryset.create(
            organization_id=self.organization.id,
            created_by=request.user,
            domain=domain,
            target_cname=settings.PROXY_TARGET_CNAME
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def destroy(self, request, *args, pk=None, **kwargs):
        queryset = self.organization.proxy_records.order_by("-created_at")
        record = queryset.get(id=pk)

        if record:
            record.status = ProxyRecord.Status.DELETING
            record.save()

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
