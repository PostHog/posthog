import json
from datetime import timedelta
from typing import Any, Optional, cast
from urllib.parse import urlparse, urlunparse

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.shortcuts import render
from django.utils.timezone import now
from django.views.decorators.clickjacking import xframe_options_exempt
from loginas.utils import is_impersonated_session
from rest_framework import mixins, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request

from posthog.api.dashboards.dashboard import DashboardSerializer
from posthog.api.data_color_theme import DataColorTheme, DataColorThemeSerializer
from posthog.api.exports import ExportedAssetSerializer
from posthog.api.insight import InsightSerializer
from posthog.api.insight_variable import InsightVariable
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client.async_task_chain import task_chain_context
from posthog.constants import AvailableFeature
from posthog.models import SessionRecording, SharingConfiguration, Team, InsightViewed
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import (
    ExportedAsset,
    asset_for_token,
    get_content_response,
)
from posthog.models.insight import Insight
from posthog.models.user import User
from posthog.session_recordings.session_recording_api import SessionRecordingSerializer
from posthog.user_permissions import UserPermissions
from posthog.utils import render_template
import secrets


def shared_url_as_png(url: str = "") -> str:
    validated_url = urlparse(url)
    path = validated_url.path

    extension = ".png"
    if not path.endswith(extension):
        path = f"{path}{extension}"

    new_url = validated_url._replace(path=path)
    return urlunparse(new_url)


# NOTE: We can't use a standard permission system as we are using Detail view on a non-detail route
def check_can_edit_sharing_configuration(
    view: "SharingConfigurationViewSet", request: Request, sharing: SharingConfiguration
) -> bool:
    if request.method in SAFE_METHODS:
        return True

    if sharing.dashboard and not view.user_permissions.dashboard(sharing.dashboard).can_edit:
        raise PermissionDenied("You don't have edit permissions for this dashboard.")

    return True


def export_asset_for_opengraph(resource: SharingConfiguration) -> ExportedAsset | None:
    serializer = ExportedAssetSerializer(
        data={
            "insight": resource.insight.pk if resource.insight else None,
            "dashboard": resource.dashboard.pk if resource.dashboard else None,
            "export_format": "image/png",
            "expires_after": now() + timedelta(hours=3),
        },
        context={"team_id": cast(Team, resource.team).pk},
    )
    serializer.is_valid(raise_exception=True)
    export_asset = serializer.synthetic_create("opengraph image")
    return export_asset


def get_themes_for_team(team: Team):
    global_and_team_themes = DataColorTheme.objects.filter(Q(team_id=team.pk) | Q(team_id=None))
    themes = DataColorThemeSerializer(global_and_team_themes, many=True).data
    return themes


class SharingConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SharingConfiguration
        fields = ["created_at", "enabled", "access_token"]
        read_only_fields = ["created_at", "access_token"]


class SharingConfigurationViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "sharing_configuration"
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "refresh"]
    pagination_class = None
    queryset = SharingConfiguration.objects.select_related("dashboard", "insight", "recording")
    serializer_class = SharingConfigurationSerializer

    def get_serializer_context(
        self,
    ) -> dict[str, Any]:
        context = super().get_serializer_context()

        dashboard_id = context.get("dashboard_id")
        insight_id = context.get("insight_id")
        recording_id = context.get("recording_id")

        if not dashboard_id and not insight_id and not recording_id:
            raise ValidationError("Either a dashboard, insight or recording must be specified")

        if dashboard_id:
            try:
                context["dashboard"] = Dashboard.objects.get(id=dashboard_id, team__project_id=self.team.project_id)
            except Dashboard.DoesNotExist:
                raise NotFound("Dashboard not found.")
        if insight_id:
            try:
                context["insight"] = Insight.objects.get(id=insight_id, team__project_id=self.team.project_id)
            except Insight.DoesNotExist:
                raise NotFound("Insight not found.")
        if recording_id:
            # NOTE: Recordings are a special case as we don't want to query CH just for this.
            context["recording"] = SessionRecording.get_or_build(recording_id, team=self.team)

        context["insight_variables"] = InsightVariable.objects.filter(team=self.team)

        return context

    def _get_sharing_configuration(self, context: dict[str, Any]):
        """
        Gets but does not create a SharingConfiguration. Only once enabled do we actually store it
        """
        context = context or self.get_serializer_context()
        dashboard = context.get("dashboard")
        insight = context.get("insight")
        recording = context.get("recording")

        config_kwargs = {
            "team_id": self.team_id,
            "insight": insight,
            "dashboard": dashboard,
            "recording": recording,
            "expires_at": None,
        }

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

        if context.get("insight"):
            name = instance.insight.name or instance.insight.derived_name
            log_activity(
                organization_id=None,
                team_id=self.team_id,
                user=cast(User, self.request.user),
                was_impersonated=is_impersonated_session(self.request),
                item_id=instance.insight.pk,
                scope="Insight",
                activity="sharing " + ("enabled" if serializer.data.get("enabled") else "disabled"),
                detail=Detail(
                    name=str(name) if name else None,
                    changes=[
                        Change(
                            type="Insight",
                            action="changed",
                            field="sharing",
                            after=serializer.data.get("enabled"),
                        )
                    ],
                    short_id=str(instance.insight.short_id),
                ),
            )

        if not context.get("recording") and serializer.data.get("enabled"):
            export_asset_for_opengraph(instance)

        return response.Response(serializer.data)

    @action(methods=["POST"], detail=False)
    def refresh(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        context = self.get_serializer_context()
        instance = self._get_sharing_configuration(context)

        check_can_edit_sharing_configuration(self, request, instance)

        # Create new sharing configuration and expire the old one
        new_instance = instance.rotate_access_token()

        if context.get("insight"):
            name = new_instance.insight.name or new_instance.insight.derived_name
            log_activity(
                organization_id=None,
                team_id=self.team_id,
                user=cast(User, self.request.user),
                was_impersonated=is_impersonated_session(self.request),
                item_id=new_instance.insight.pk,
                scope="Insight",
                activity="access token refreshed",
                detail=Detail(
                    name=str(name) if name else None,
                    short_id=str(new_instance.insight.short_id),
                ),
            )

        serializer = self.get_serializer(new_instance)
        return response.Response(serializer.data)


def custom_404_response(request):
    """Returns a custom 404 page."""
    return render(request, "shared_resource_404.html", status=404)


class SharingViewerPageViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    NOTE: This ViewSet takes care of multiple rendering cases:
    1. Shared Resources like Shared Dashboard or Insight
    2. Embedded Resources (same as sharing but with slightly modified UI)
    3. Export Rendering - used by the worker to load a webpage for taking an image screenshot of
    4. Export downloading - used to download the actual content of an export if requested with the correct extension
    """

    authentication_classes = []
    permission_classes = []

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
            # Find non-expired configuration (expires_at is NULL for active, or in the future for grace period)
            sharing_configuration = (
                SharingConfiguration.objects.select_related("dashboard", "insight", "recording")
                .filter(
                    access_token=access_token,
                    enabled=True,
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now()))
                .first()
            )

            if sharing_configuration:
                return sharing_configuration

        return None

    @xframe_options_exempt
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        try:
            resource = self.get_object()
        except NotFound:
            resource = None

        if not resource:
            return custom_404_response(self.request)

        embedded = "embedded" in request.GET or "/embedded/" in request.path
        context = {
            "view": self,
            "request": request,
            "user_permissions": UserPermissions(cast(User, request.user), resource.team),
            "is_shared": True,
            "get_team": lambda: resource.team,
            "insight_variables": InsightVariable.objects.filter(team=resource.team).all(),
        }
        exported_data: dict[str, Any] = {"type": "embed" if embedded else "scene"}

        if isinstance(resource, SharingConfiguration) and request.path.endswith(f".png"):
            exported_data["accessToken"] = resource.access_token
            exported_asset = self.exported_asset_for_sharing_configuration(resource)
            if not exported_asset:
                raise NotFound()
            return get_content_response(exported_asset, False)
        elif isinstance(resource, SharingConfiguration):
            exported_data["accessToken"] = resource.access_token
        elif isinstance(resource, ExportedAsset):
            if request.path.endswith(f".{resource.file_ext}"):
                return get_content_response(resource, request.query_params.get("download") == "true")
            exported_data["type"] = "image"

        add_og_tags = resource.insight or resource.dashboard
        asset_description = ""

        if resource.insight and not resource.insight.deleted:
            # Both insight AND dashboard can be set. If both it is assumed we should render that
            context["dashboard"] = resource.dashboard
            asset_title = resource.insight.name or resource.insight.derived_name
            asset_description = resource.insight.description or ""
            InsightViewed.objects.update_or_create(
                insight=resource.insight, team=None, user=None, defaults={"last_viewed_at": now()}
            )
            insight_data = InsightSerializer(resource.insight, many=False, context=context).data
            exported_data.update({"insight": insight_data})
            exported_data.update({"themes": get_themes_for_team(resource.team)})
        elif resource.dashboard and not resource.dashboard.deleted:
            asset_title = resource.dashboard.name
            asset_description = resource.dashboard.description or ""
            resource.dashboard.last_accessed_at = now()
            resource.dashboard.save(update_fields=["last_accessed_at"])
            with task_chain_context():
                dashboard_data = DashboardSerializer(resource.dashboard, context=context).data
                # We don't want the dashboard to be accidentally loaded via the shared endpoint
                exported_data.update({"dashboard": dashboard_data})
            exported_data.update({"themes": get_themes_for_team(resource.team)})
        elif (
            isinstance(resource, ExportedAsset) and resource.export_context and resource.export_context.get("replay_id")
        ):
            # Handle replay export via export_context
            replay_id = resource.export_context.get("replay_id")
            timestamp = resource.export_context.get("timestamp")

            if not replay_id:
                raise NotFound("Invalid replay export - missing replay_id")

            # Create a SessionRecording object for the replay
            try:
                # First, try to get existing recording from database
                try:
                    recording = SessionRecording.objects.get(session_id=replay_id, team=resource.team)
                except SessionRecording.DoesNotExist:
                    # If not found, create it properly
                    recording = SessionRecording(session_id=replay_id, team=resource.team)
                    recording.save()  # This ensures it exists in PostgreSQL

                # Now create sharing configuration
                sharing_config, created = SharingConfiguration.objects.get_or_create(
                    team=resource.team,
                    recording=recording,
                    defaults={
                        "enabled": True,
                        "access_token": secrets.token_urlsafe(32),
                    },
                )
                asset_title = "Session Recording"
                asset_description = f"Recording {replay_id}"

                recording_data = SessionRecordingSerializer(recording, context=context).data

                exported_data.update(
                    {
                        "type": "replay_export",
                        "recording": recording_data,
                        "timestamp": timestamp,
                        "replay_id": replay_id,
                        "accessToken": sharing_config.access_token,
                        "noBorder": True,
                    }
                )

            except Exception as e:
                raise NotFound(f"Could not load replay {replay_id}: {str(e)}")
        elif isinstance(resource, SharingConfiguration) and resource.recording and not resource.recording.deleted:
            asset_title = "Session Recording"
            recording_data = SessionRecordingSerializer(resource.recording, context=context).data
            exported_data.update({"recording": recording_data})
        else:
            raise NotFound()

        if "whitelabel" in request.GET and resource.team.organization.is_feature_available(
            AvailableFeature.WHITE_LABELLING
        ):
            exported_data.update({"whitelabel": True})
        if "noHeader" in request.GET:
            exported_data.update({"noHeader": True})
        if "showInspector" in request.GET:
            exported_data.update({"showInspector": True})
        if "legend" in request.GET:
            exported_data.update({"legend": True})
        if "detailed" in request.GET:
            exported_data.update({"detailed": True})

        if request.path.endswith(f".json"):
            return response.Response(exported_data)

        if request.GET.get("force_type"):
            exported_data["type"] = request.GET.get("force_type")

        exported_data["rootClassName"] = f"export-type-'{exported_data.get('type', 'unknown')}"

        return render_template(
            "exporter.html",
            request=request,
            context={
                "exported_data": json.dumps(exported_data, cls=DjangoJSONEncoder),
                "asset_title": asset_title,
                "asset_description": asset_description,
                "add_og_tags": add_og_tags,
                "asset_opengraph_image_url": shared_url_as_png(request.build_absolute_uri()),
            },
            team_for_public_context=resource.team,
        )

    def exported_asset_for_sharing_configuration(self, resource: SharingConfiguration) -> ExportedAsset | None:
        target = resource.insight or resource.dashboard
        if not target:
            return None

        exported_asset_matches = ExportedAsset.objects.filter(
            team=resource.team,
            insight=resource.insight or None,
            dashboard=resource.dashboard or None,
            export_format=ExportedAsset.ExportFormat.PNG.value,
        )

        if exported_asset_matches.exists():
            return exported_asset_matches.first()
        else:
            export_asset = export_asset_for_opengraph(resource)

            return export_asset
