import json
from typing import Any, Dict, Optional, cast

from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import mixins, response, serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.request import Request

from posthog.api.dashboards.dashboard import DashboardSerializer
from posthog.api.insight import InsightSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.session_recording import SessionRecordingSerializer
from posthog.models import SharingConfiguration
from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset, asset_for_token, get_content_response
from posthog.models.insight import Insight
from posthog.models.session_recording import SessionRecording
from posthog.models.user import User
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.user_permissions import UserPermissions
from posthog.utils import render_template


# NOTE: We can't use a standard permission system as we are using Detail view on a non-detail route
def check_can_edit_sharing_configuration(
    view: "SharingConfigurationViewSet", request: Request, sharing: SharingConfiguration
) -> bool:
    if request.method in SAFE_METHODS:
        return True

    if sharing.dashboard and not view.user_permissions.dashboard(sharing.dashboard).can_edit:
        raise PermissionDenied("You don't have edit permissions for this dashboard.")

    return True


class SharingConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SharingConfiguration
        fields = ["created_at", "enabled", "access_token"]
        read_only_fields = ["created_at", "access_token"]


class SharingConfigurationViewSet(StructuredViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    pagination_class = None
    queryset = SharingConfiguration.objects.select_related("dashboard", "insight", "recording")
    serializer_class = SharingConfigurationSerializer
    include_in_docs = False

    def get_serializer_context(
        self,
    ) -> Dict[str, Any]:
        context = super().get_serializer_context()

        dashboard_id = context.get("dashboard_id")
        insight_id = context.get("insight_id")
        recording_id = context.get("recording_id")

        if not dashboard_id and not insight_id and not recording_id:
            raise ValidationError("Either a dashboard, insight or recording must be specified")

        if dashboard_id:
            try:
                context["dashboard"] = Dashboard.objects.get(id=dashboard_id, team=self.team)
            except Dashboard.DoesNotExist:
                raise NotFound("Dashboard not found.")
        if insight_id:
            try:
                context["insight"] = Insight.objects.get(id=insight_id, team=self.team)
            except Insight.DoesNotExist:
                raise NotFound("Insight not found.")
        if recording_id:
            # NOTE: Recordings are a special case as we don't want to query CH just for this.
            context["recording"] = SessionRecording.get_or_build(recording_id, team=self.team)

        return context

    def _get_sharing_configuration(self, context: Dict[str, Any]):
        """
        Gets but does not create a SharingConfiguration. Only once enabled do we actually store it
        """
        context = context or self.get_serializer_context()
        dashboard = context.get("dashboard")
        insight = context.get("insight")
        recording = context.get("recording")

        config_kwargs = dict(team_id=self.team_id, insight=insight, dashboard=dashboard, recording=recording)

        try:
            instance = SharingConfiguration.objects.get(**config_kwargs)
        except SharingConfiguration.DoesNotExist:
            instance = SharingConfiguration(**config_kwargs)

        if dashboard:
            # Ensure the legacy dashboard fields are in sync with the sharing configuration
            if dashboard.share_token and dashboard.share_token != instance.access_token:
                instance.enabled = dashboard.is_shared
                instance.access_token = dashboard.share_token
                instance.save()

        return instance

    def list(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        context = self.get_serializer_context()
        instance = self._get_sharing_configuration(context)

        serializer = self.get_serializer(instance, context)
        serializer.is_valid(raise_exception=True)

        return response.Response(serializer.data)

    def patch(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        context = self.get_serializer_context()
        instance = self._get_sharing_configuration(context)

        check_can_edit_sharing_configuration(self, request, instance)

        if context.get("recording"):
            recording = cast(SessionRecording, context.get("recording"))
            # Special case where we need to save the instance for recordings so that the actual record gets created
            recording.save()

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return response.Response(serializer.data)


class SharingViewerPageViewSet(mixins.RetrieveModelMixin, StructuredViewSetMixin, viewsets.GenericViewSet):
    """
    NOTE: This ViewSet takes care of multiple rendering cases:
    1. Shared Resources like Shared Dashboard or Insight
    2. Embedded Resources (same as sharing but with slightly modified UI)
    3. Export Rendering - used by the worker to load a webpage for taking an image screenshot of
    4. Export downloading - used to download the actual content of an export if requested with the correct extension
    """

    authentication_classes = []  # type: ignore
    permission_classes = []  # type: ignore
    include_in_docs = False

    def get_object(self) -> Optional[SharingConfiguration | ExportedAsset]:
        # JWT based access (ExportedAsset)
        token = self.request.query_params.get("token")
        if token:
            asset = asset_for_token(token)
            if asset:
                return asset

        # Path based access (SharingConfiguration only)
        access_token = self.kwargs.get("access_token", "").split(".")[0]
        if access_token:
            sharing_configuration = None
            try:
                sharing_configuration = SharingConfiguration.objects.select_related(
                    "dashboard", "insight", "recording"
                ).get(access_token=access_token)
            except SharingConfiguration.DoesNotExist:
                raise NotFound()

            if sharing_configuration and sharing_configuration.enabled:
                return sharing_configuration

        return None

    @xframe_options_exempt
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        resource = self.get_object()

        if not resource:
            raise NotFound()

        embedded = "embedded" in request.GET or "/embedded/" in request.path
        context = {
            "view": self,
            "request": request,
            "user_permissions": UserPermissions(cast(User, request.user), resource.team),
            "is_shared": True,
        }
        exported_data: Dict[str, Any] = {"type": "embed" if embedded else "scene"}

        if isinstance(resource, SharingConfiguration):
            exported_data["accessToken"] = resource.access_token
        elif isinstance(resource, ExportedAsset):
            if request.path.endswith(f".{resource.file_ext}"):
                return get_content_response(resource, request.query_params.get("download") == "true")
            exported_data["type"] = "image"

        if resource.insight and not resource.insight.deleted:
            # Both insight AND dashboard can be set. If both it is assumed we should render that
            context["dashboard"] = resource.dashboard
            insight_data = InsightSerializer(resource.insight, many=False, context=context).data
            exported_data.update({"insight": insight_data})
        elif resource.dashboard and not resource.dashboard.deleted:
            dashboard_data = DashboardSerializer(resource.dashboard, context=context).data
            # We don't want the dashboard to be accidentally loaded via the shared endpoint
            exported_data.update({"dashboard": dashboard_data})
        elif isinstance(resource, SharingConfiguration) and resource.recording and not resource.recording.deleted:
            recording_data = SessionRecordingSerializer(resource.recording, context=context).data
            exported_data.update({"recording": recording_data})
        else:
            raise NotFound()

        if "whitelabel" in request.GET and "white_labelling" in resource.team.organization.available_features:
            exported_data.update({"whitelabel": True})
        if "noHeader" in request.GET:
            exported_data.update({"noHeader": True})
        if "showInspector" in request.GET:
            exported_data.update({"showInspector": True})
        if "legend" in request.GET:
            exported_data.update({"legend": True})

        if request.path.endswith(f".json"):
            return response.Response(exported_data)

        if request.GET.get("force_type"):
            exported_data["type"] = request.GET.get("force_type")

        return render_template(
            "exporter.html",
            request=request,
            context={"exported_data": json.dumps(exported_data, cls=DjangoJSONEncoder)},
            team_for_public_context=resource.team,
        )
