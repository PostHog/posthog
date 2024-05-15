from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import ProxyRecord
from posthog.permissions import OrganizationAdminWritePermissions
from rest_framework.response import Response

DOMAIN_REGEX = r"^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$"


class ProxyRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyRecord
        fields = (
            "id",
            "domain",
            # "dns_records",
            # "status",
        )
        # read_only_fields = ("dns_records", "status")


class ProxyRecordViewset(TeamAndOrgViewSetMixin, ModelViewSet):
    scope_object = "organization"
    serializer_class = ProxyRecordSerializer
    permission_classes = [OrganizationAdminWritePermissions]
    queryset = ProxyRecord.objects.order_by("domain").all()

    def list(self, request, *args, **kwargs):
        queryset = self.organization.proxy_records
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        domain = request.data.get("domain")
        queryset = self.organization.proxy_records
        queryset.create(domain=domain)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
