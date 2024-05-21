import hashlib
from django.conf import settings
from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import ProxyRecord
from posthog.permissions import OrganizationAdminWritePermissions
from rest_framework.response import Response


def generate_target_cname(organization_id, domain) -> str:
    m = hashlib.sha256()
    m.update(f"{organization_id}".encode())
    m.update(domain.encode())
    digest = m.hexdigest()[:20]
    return f"{digest}.{settings.PROXY_BASE_CNAME}"


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
            target_cname=generate_target_cname(self.organization.id, domain),
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def destroy(self, request, *args, pk=None, **kwargs):
        record = self.organization.proxy_records.get(id=pk)

        if record and record.status in (ProxyRecord.Status.WAITING, ProxyRecord.Status.ERRORING):
            record.delete()
        elif record:
            record.status = ProxyRecord.Status.DELETING
            record.save()

        serializer = self.get_serializer(record)
        return Response(serializer.data)
