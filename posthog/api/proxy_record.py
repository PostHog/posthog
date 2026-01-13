import asyncio
import hashlib

from django.conf import settings

import posthoganalytics
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups
from posthog.models import ProxyRecord
from posthog.models.organization import Organization
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission
from posthog.temporal.common.client import sync_connect
from posthog.temporal.proxy_service import CreateManagedProxyInputs, DeleteManagedProxyInputs


def generate_target_cname(organization_id, domain) -> str:
    from posthog.temporal.proxy_service.common import use_cloudflare_proxy

    m = hashlib.sha256()
    m.update(f"{organization_id}".encode())
    m.update(domain.encode())
    digest = m.hexdigest()[:20]

    # Check if this specific org should use Cloudflare
    if use_cloudflare_proxy(organization_id):
        base_cname = settings.CLOUDFLARE_PROXY_BASE_CNAME
    else:
        base_cname = settings.PROXY_BASE_CNAME

    return f"{digest}.{base_cname}"


def _capture_proxy_event(request, record: ProxyRecord, event_type: str) -> None:
    organization = Organization.objects.get(id=record.organization_id)
    posthoganalytics.capture(
        distinct_id=str(request.user.distinct_id),
        event=f"managed reverse proxy {event_type}",
        properties={
            "proxy_record_id": record.id,
            "domain": record.domain,
            "target_cname": record.target_cname,
        },
        groups=groups(organization),
    )


class ProxyRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProxyRecord
        fields = (
            "id",
            "domain",
            "target_cname",
            "status",
            "message",
            "created_at",
            "updated_at",
            "created_by",
        )
        read_only_fields = ("target_cname", "created_at", "created_by", "status", "message")


class ProxyRecordViewset(TeamAndOrgViewSetMixin, ModelViewSet):
    scope_object = "organization"
    serializer_class = ProxyRecordSerializer
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]

    def list(self, request, *args, **kwargs):
        queryset = self.organization.proxy_records.order_by("-created_at")
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        domain = request.data.get("domain")
        queryset = self.organization.proxy_records.order_by("-created_at")
        record = queryset.create(
            organization_id=self.organization.id,
            created_by=request.user,
            domain=domain,
            target_cname=generate_target_cname(self.organization.id, domain),
        )

        temporal = sync_connect()
        inputs = CreateManagedProxyInputs(
            organization_id=record.organization_id,
            proxy_record_id=record.id,
            domain=record.domain,
            target_cname=record.target_cname,
        )
        workflow_id = f"proxy-create-{inputs.proxy_record_id}"
        asyncio.run(
            temporal.start_workflow(
                "create-proxy",
                inputs,
                id=workflow_id,
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            )
        )

        serializer = self.get_serializer(record)
        _capture_proxy_event(request, record, "created")
        return Response(serializer.data)

    def destroy(self, request, *args, pk=None, **kwargs):
        record = self.organization.proxy_records.get(id=pk)

        if record and record.status in (
            ProxyRecord.Status.WAITING,
            ProxyRecord.Status.ERRORING,
            ProxyRecord.Status.TIMED_OUT,
        ):
            record.delete()
        elif record:
            temporal = sync_connect()
            inputs = DeleteManagedProxyInputs(
                organization_id=record.organization_id,
                proxy_record_id=record.id,
                domain=record.domain,
                target_cname=record.target_cname,
            )
            workflow_id = f"proxy-delete-{inputs.proxy_record_id}"
            asyncio.run(
                temporal.start_workflow(
                    "delete-proxy",
                    inputs,
                    id=workflow_id,
                    task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                )
            )
            record.status = ProxyRecord.Status.DELETING
            record.save()

            _capture_proxy_event(request, record, "deleted")

        return Response(
            {"success": True},
            status=status.HTTP_200_OK,
        )
