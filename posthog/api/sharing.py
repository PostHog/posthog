from typing import Any, Dict

from rest_framework import mixins, response, serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.api.routing import StructuredViewSetMixin
from posthog.models import SharingConfiguration
from posthog.models.dashboard import Dashboard
from posthog.models.insight import Insight
from posthog.permissions import TeamMemberAccessPermission


class SharingConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SharingConfiguration
        fields = ["created_at", "enabled", "access_token"]
        read_only_fields = ["created_at", "access_token"]


class SharingConfigurationViewSet(
    StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet, mixins.UpdateModelMixin,
):
    permission_classes = [IsAuthenticated, TeamMemberAccessPermission]
    pagination_class = None
    queryset = SharingConfiguration.objects.select_related("dashboard", "insight")
    serializer_class = SharingConfigurationSerializer
    include_in_docs = False

    def get_serializer_context(self) -> Dict[str, Any]:
        context = super().get_serializer_context()

        dashboard_id = context.get("dashboard_id")
        insight_id = context.get("insight_id")

        if not dashboard_id and not insight_id:
            raise ValidationError("Either a dashboard or insight must be specified")

        if dashboard_id:
            try:
                context["dashboard"] = Dashboard.objects.get(id=dashboard_id)
            except Dashboard.DoesNotExist:
                raise NotFound("Dashboard not found.")
        if insight_id:
            try:
                context["insight"] = Insight.objects.get(id=insight_id)
            except Insight.DoesNotExist:
                raise NotFound("Insight not found.")

        return context

    def list(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        context = self.get_serializer_context()
        instance, created = SharingConfiguration.objects.get_or_create(
            insight_id=context.get("insight_id"), dashboard_id=context.get("dashboard_id"), team_id=self.team_id
        )

        serializer = self.get_serializer(instance, context)
        serializer.is_valid(raise_exception=True)

        return response.Response(serializer.data)

    def patch(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        context = self.get_serializer_context()

        instance, created = SharingConfiguration.objects.get_or_create(
            insight_id=context.get("insight_id"), dashboard_id=context.get("dashboard_id"), team_id=self.team_id
        )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return response.Response(serializer.data)


# @xframe_options_exempt
# def shared_resource(request: HttpRequest, share_token: str):
#     exported_data: Dict[str, Any] = {
#         "type": "embed" if "embedded" in request.GET else "scene",
#         "dashboard": {
#             "id": dashboard.id,
#             "share_token": dashboard.share_token,
#             "name": dashboard.name,
#             "description": dashboard.description,
#         },
#         "team": {"name": dashboard.team.name},
#     }

#     if "whitelabel" in request.GET and "white_labelling" in dashboard.team.organization.available_features:
#         exported_data.update({"whitelabel": True})

#     return render_template("exporter.html", request=request, context={"exported_data": json.dumps(exported_data)},)


# class SharingViewerPageViewSet(mixins.RetrieveModelMixin, StructuredViewSetMixin, viewsets.GenericViewSet):
#     queryset = SharingConfiguration.objects.none()
#     authentication_classes = []  # type: ignore
#     permission_classes = []  # type: ignore

#     def get_object(self):
#         token = self.request.query_params.get("token")
#         access_token = self.kwargs.get("access_token")

#         resource = None

#         if token:
#             pass
#             # TODO: Load resource based on token contents
#             # asset = asset_for_token(token)
#         else:
#             sharing_configuration = SharingConfiguration.objects.get(access_token=access_token)

#             if sharing_configuration and sharing_configuration.enabled:
#                 resource = sharing_configuration.insight or sharing_configuration.dashboard

#         if not resource:
#             raise serializers.NotFound()

#         return resource

#     def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Any:
#         resource = self.get_object()
#         context = {"view": self, "request": request}
#         exported_data: Dict[str, Any] = {"type": "image"}

#         if request.path.endswith(f".{asset.file_ext}"):
#             if not asset.content:
#                 raise serializers.NotFound()

#             return get_content_response(asset, request.query_params.get("download") == "true")

#         if asset.dashboard:
#             dashboard_data = DashboardSerializer(asset.dashboard, context=context).data
#             # We don't want the dashboard to be accidentally loaded via the shared endpoint
#             dashboard_data["share_token"] = None
#             exported_data.update({"dashboard": dashboard_data})

#         if asset.insight:
#             insight_data = InsightSerializer(asset.insight, many=False, context=context).data
#             exported_data.update({"insight": insight_data})

#         return render_template(
#             "exporter.html",
#             request=request,
#             context={"exported_data": json.dumps(exported_data, cls=DjangoJSONEncoder)},
#         )
