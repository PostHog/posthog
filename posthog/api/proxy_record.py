import time
import asyncio
import hashlib

from django.conf import settings

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import ProxyRecord
from posthog.models.organization import Organization
from posthog.permissions import OrganizationAdminWritePermissions, TimeSensitiveActionPermission
from posthog.temporal.common.client import sync_connect
from posthog.temporal.proxy_service import CreateManagedProxyInputs, DeleteManagedProxyInputs


def generate_target_cname(organization_id, domain) -> str:
    m = hashlib.sha256()
    m.update(f"{organization_id}".encode())
    m.update(domain.encode())
    digest = m.hexdigest()[:20]
    base_cname = (
        settings.CLOUDFLARE_PROXY_BASE_CNAME if settings.CLOUDFLARE_PROXY_ENABLED else settings.PROXY_BASE_CNAME
    )
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

    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for the proxy record.")
    domain = serializers.CharField(
        help_text="The custom domain to proxy through, e.g. 'e.example.com'. Must be a valid subdomain you control."
    )
    target_cname = serializers.CharField(
        read_only=True,
        help_text="The CNAME target to add as a DNS record for your domain. Point your domain's CNAME to this value.",
    )
    status = serializers.ChoiceField(
        choices=ProxyRecord.Status.choices,
        read_only=True,
        help_text=(
            "Current provisioning status. "
            "Values: waiting (DNS verification pending), issuing (SSL certificate being issued), "
            "valid (proxy is live and working), warning (proxy has issues but is operational), "
            "erroring (proxy setup failed), deleting (removal in progress), timed_out (DNS verification timed out)."
        ),
    )
    message = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Human-readable status message with details about errors or warnings, if any.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When this proxy record was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When this proxy record was last updated.")
    created_by: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(  # ty: ignore[invalid-assignment]
        read_only=True, help_text="ID of the user who created this proxy record."
    )


class ProxyRecordListResponseSerializer(serializers.Serializer):
    results = ProxyRecordSerializer(many=True)
    max_proxy_records = serializers.IntegerField(
        help_text="Maximum number of proxy records allowed for this organization's current plan."
    )


@extend_schema(tags=["reverse_proxy"])
class ProxyRecordViewset(TeamAndOrgViewSetMixin, ModelViewSet):
    scope_object = "organization"
    serializer_class = ProxyRecordSerializer
    permission_classes = [OrganizationAdminWritePermissions, TimeSensitiveActionPermission]
    queryset = ProxyRecord.objects.order_by("-created_at")
    pagination_class = None
    http_method_names = ["get", "post", "delete"]

    DEFAULT_MAX_PROXY_RECORDS = 2

    @property
    def max_proxy_records(self) -> int:
        feature = self.organization.get_available_feature(AvailableFeature.MANAGED_REVERSE_PROXY)
        if feature is None:
            # Allow a default quota even without the billing feature so existing
            # orgs aren't broken if they haven't migrated to a plan that includes it
            return self.DEFAULT_MAX_PROXY_RECORDS
        limit = feature.get("limit")
        return limit if limit is not None else self.DEFAULT_MAX_PROXY_RECORDS

    @extend_schema(
        description="List all reverse proxies configured for the organization. "
        "Returns proxy records along with the maximum number allowed by the current plan.",
        responses={200: ProxyRecordListResponseSerializer},
    )
    def list(self, request, *args, **kwargs):
        queryset = self.organization.proxy_records.order_by("-created_at")
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "results": serializer.data,
                "max_proxy_records": self.max_proxy_records,
            }
        )

    @extend_schema(
        description="Get details of a specific reverse proxy by ID. "
        "Returns the full configuration including domain, CNAME target, and current provisioning status.",
    )
    def retrieve(self, request, *args, pk=None, **kwargs):
        try:
            record = self.organization.proxy_records.get(id=pk)
        except ProxyRecord.DoesNotExist:
            raise NotFound()
        serializer = self.get_serializer(record)
        return Response(serializer.data)

    @extend_schema(
        description="Create a new managed reverse proxy. "
        "Provide the domain you want to proxy through. "
        "The response includes the CNAME target you need to add as a DNS record. "
        "Once the CNAME is configured, the proxy will be automatically verified and provisioned.",
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        domain = serializer.validated_data["domain"]

        queryset = self.organization.proxy_records.order_by("-created_at")

        max_records = self.max_proxy_records
        if queryset.count() >= max_records:
            return Response(
                {"detail": f"Maximum of {max_records} proxy records per organization."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record = queryset.create(
            organization_id=self.organization.id,
            created_by=request.user,
            domain=domain,
            target_cname=generate_target_cname(self.organization.id, domain),
        )

        try:
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
        except Exception as e:
            capture_exception(e, {"domain": record.domain, "proxy_record_id": str(record.id)})
            record.delete()
            return Response(
                {"detail": "Failed to start provisioning workflow."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        serializer = self.get_serializer(record)
        _capture_proxy_event(request, record, "created")
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        description="Retry provisioning a failed reverse proxy. "
        "Only available for proxies in 'erroring' or 'timed_out' status. "
        "Resets the proxy to 'waiting' status and restarts the provisioning workflow.",
        request=None,
    )
    @action(methods=["POST"], detail=True)
    def retry(self, request, *args, pk=None, **kwargs):
        try:
            record = self.organization.proxy_records.get(id=pk)
        except ProxyRecord.DoesNotExist:
            raise NotFound()

        if record.status not in (
            ProxyRecord.Status.ERRORING,
            ProxyRecord.Status.TIMED_OUT,
        ):
            return Response(
                {"detail": f"Cannot retry proxy in {record.status} state."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record.status = ProxyRecord.Status.WAITING
        record.message = None
        record.save()

        try:
            temporal = sync_connect()
            inputs = CreateManagedProxyInputs(
                organization_id=record.organization_id,
                proxy_record_id=record.id,
                domain=record.domain,
                target_cname=record.target_cname,
            )
            workflow_id = f"proxy-create-{inputs.proxy_record_id}-retry-{int(time.time())}"
            asyncio.run(
                temporal.start_workflow(
                    "create-proxy",
                    inputs,
                    id=workflow_id,
                    task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                )
            )
        except Exception as e:
            capture_exception(e, {"domain": record.domain, "proxy_record_id": str(record.id)})
            record.status = ProxyRecord.Status.ERRORING
            record.save()
            return Response(
                {"detail": "Failed to start retry workflow."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        serializer = self.get_serializer(record)
        _capture_proxy_event(request, record, "retried")
        return Response(serializer.data)

    @extend_schema(
        description="Delete a reverse proxy. "
        "For proxies in 'waiting', 'erroring', or 'timed_out' status, the record is deleted immediately. "
        "For active proxies, a deletion workflow is started to clean up the provisioned infrastructure.",
    )
    def destroy(self, request, *args, pk=None, **kwargs):
        try:
            record = self.organization.proxy_records.get(id=pk)
        except ProxyRecord.DoesNotExist:
            raise NotFound()

        if record.status in (
            ProxyRecord.Status.WAITING,
            ProxyRecord.Status.ERRORING,
            ProxyRecord.Status.TIMED_OUT,
        ):
            _capture_proxy_event(request, record, "deleted")
            record.delete()
        else:
            previous_status = record.status
            record.status = ProxyRecord.Status.DELETING
            record.save()

            try:
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
            except Exception as e:
                capture_exception(e, {"domain": record.domain, "proxy_record_id": str(record.id)})
                record.status = previous_status
                record.save()
                return Response(
                    {"detail": "Failed to start deletion workflow."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            _capture_proxy_event(request, record, "deleted")

        return Response(
            {"success": True},
            status=status.HTTP_200_OK,
        )
