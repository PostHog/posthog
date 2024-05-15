import structlog
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

logger = structlog.get_logger(__name__)


class ReferralProgramSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = ReferralProgram
        fields = ["short_id", "title", "created_at", "created_by"]
        read_only_fields = ["short_id", "created_at", "created_by"]


class ReferralProgramViewset(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    # scope_object = "referrals"
    queryset = ReferrerProgram.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["short_id"]
    lookup_field = "short_id"
    serializer_class = ReferralProgramSerializer

    # def safely_get_queryset(self, queryset) -> QuerySet:
    #     if not self.action.endswith("update"):
    #         # Soft-deleted notebooks can be brought back with a PATCH request
    #         queryset = queryset.filter(deleted=False)

    #     queryset = queryset.select_related("created_by", "last_modified_by", "team")
    #     if self.action == "list":
    #         queryset = queryset.filter(deleted=False)
    #         queryset = self._filter_list_request(self.request, queryset)

    #     order = self.request.GET.get("order", None)
    #     if order:
    #         queryset = queryset.order_by(order)
    #     else:
    #         queryset = queryset.order_by("-last_modified_at")

    #     return queryset

    # def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
    #     instance = self.get_object()
    #     serializer = self.get_serializer(instance)

    #     if str(request.headers.get("If-None-Match")) == str(instance.version):
    #         return Response(None, 304)

    #     return Response(serializer.data)
