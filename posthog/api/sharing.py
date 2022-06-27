from typing import Any, Dict, Sequence, Type, Union, cast

from django.db.models import Prefetch, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import exceptions, mixins, response, serializers, viewsets, request
from rest_framework.authentication import BaseAuthentication, BasicAuthentication, SessionAuthentication
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated, OperandHolder, SingleOperandHolder
from rest_framework.request import Request
from posthog.api.routing import StructuredViewSetMixin

from posthog.constants import INSIGHT_TRENDS
from posthog.event_usage import report_user_action
from posthog.helpers import create_dashboard_from_template
from posthog.models import SharingConfiguration, sharing_configuration
from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import asset_for_token
from posthog.models.insight import Insight
from posthog.models.user import User
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.utils import render_template


class SharingConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SharingConfiguration
        fields = ["id", "dashboard", "insight", "created_at", "enabled", "access_token"]
        read_only_fields = ["dashboard", "insight", "created_at", "access_token"]


def get_sharing_configuration(view: StructuredViewSetMixin, insight: Insight = None, dashboard: Dashboard = None):
    sharing_configuration, created = SharingConfiguration.objects.get_or_create(
        insight=insight, dashboard=dashboard, team_id=view.team_id
    )

    serializer = SharingConfigurationSerializer(sharing_configuration, context={"view": view, "request": view.request})
    return response.Response({"result": serializer.data})


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
