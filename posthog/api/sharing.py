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
from rest_framework import mixins, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request

from posthog.schema import SharingConfigurationSettings

from posthog.api.dashboards.dashboard import DashboardSerializer
from posthog.api.data_color_theme import DataColorTheme, DataColorThemeSerializer
from posthog.api.exports import ExportedAssetSerializer
from posthog.api.insight import InsightSerializer
from posthog.api.insight_variable import InsightVariable
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import TeamPublicSerializer
from posthog.auth import SharingAccessTokenAuthentication, SharingPasswordProtectedAuthentication
from posthog.clickhouse.client.async_task_chain import task_chain_context
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import InsightViewed, SessionRecording, SharePassword, SharingConfiguration, Team
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset, asset_for_token, get_content_response
from posthog.models.insight import Insight
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource
from posthog.session_recordings.session_recording_api import SessionRecordingSerializer
from posthog.user_permissions import UserPermissions
from posthog.utils import get_ip_address, render_template
from posthog.views import preflight_check


def shared_url_as_png(url: str = "") -> str:
    validated_url = urlparse(url)
    path = validated_url.path

    extension = ".png"
    if not path.endswith(extension):
        path = f"{path}{extension}"

    new_url = validated_url._replace(path=path)
    return urlunparse(new_url)


def _log_share_password_attempt(
    resource: SharingConfiguration, request: Request, success: bool, validated_password: Optional[SharePassword] = None
) -> None:
    """Log password validation attempts for sharing configurations"""
    client_ip = get_ip_address(request) or "unknown"

    if resource.dashboard:
        scope = "Dashboard"
        item_id = str(resource.dashboard.id)
        resource_type = "dashboard"
        resource_name = resource.dashboard.name
    elif resource.insight:
        scope = "Insight"
        item_id = str(resource.insight.id)
        resource_type = "insight"
        resource_name = resource.insight.name
    else:
        return

    base_params = {
        "organization_id": resource.team.organization.id,
        "team_id": resource.team.id,
        "user": None,
        "was_impersonated": False,
        "item_id": item_id,
        "scope": scope,
    }

    change_data = {
        "access_token_suffix": resource.access_token[-6:] if resource.access_token else None,
        "client_ip": client_ip,
        "success": success,
        "resource_type": resource_type,
    }

    if success and validated_password:
        change_data["password_id"] = str(validated_password.id)
        change_data["password_note"] = validated_password.note or "Untitled password"
        activity_name = "share_login_success"
        detail_name = resource_name
    else:
        activity_name = "share_login_failed"
        detail_name = resource_name

    log_activity(
        **base_params,
        activity=activity_name,
        detail=Detail(
            name=detail_name,
            changes=[
                Change(
                    type=scope,  # Use the same scope as the activity log (Dashboard/Insight/Replay)
                    action="changed",
                    field="authentication_attempt",
                    after=change_data,
                )
            ],
        ),
    )


# NOTE: We can't use a standard permission system as we are using Detail view on a non-detail route
def check_can_edit_sharing_configuration(
    view: "SharingConfigurationViewSet", request: Request, sharing: SharingConfiguration
) -> bool:
    if request.method in SAFE_METHODS:
        return True

    # Check if organization allows publicly shared resources
    if (
        request.data.get("enabled")
        and sharing.team.organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)
        and not sharing.team.organization.allow_publicly_shared_resources
    ):
        raise PermissionDenied("Public sharing is disabled for this organization.")

    user_access_control = UserAccessControl(cast(User, request.user), team=view.team)

    if sharing.dashboard:
        # Legacy check: remove once all users are on the new access control
        if sharing.dashboard.restriction_level > Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT:
            if not view.user_permissions.dashboard(sharing.dashboard).can_edit:
                raise PermissionDenied("You don't have edit permissions for this dashboard.")
        else:
            access_level = user_access_control.get_user_access_level(sharing.dashboard)
            if not access_level or not access_level_satisfied_for_resource("dashboard", access_level, "editor"):
                raise PermissionDenied("You don't have edit permissions for this dashboard.")

    if sharing.insight:
        access_level = user_access_control.get_user_access_level(sharing.insight)
        if not access_level or not access_level_satisfied_for_resource("insight", access_level, "editor"):
            raise PermissionDenied("You don't have edit permissions for this insight.")

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


def get_global_themes():
    global_themes = DataColorTheme.objects.filter(Q(team_id=None))
    themes = DataColorThemeSerializer(global_themes, many=True).data
    return themes


def build_shared_app_context(team: Team, request: Request) -> dict[str, Any]:
    """
    Build app context for shared dashboards/insights similar to what render_template creates.
    This provides the same structure as window.POSTHOG_APP_CONTEXT.
    """
    from django.conf import settings

    from posthog.utils import get_git_commit_short

    return {
        "current_user": None,
        "current_project": None,
        "current_team": TeamPublicSerializer(team, context={"request": request}, many=False).data,
        "preflight": json.loads(preflight_check(request).getvalue()),
        "default_event_name": "$pageview",
        "switched_team": None,
        "suggested_users_with_access": None,
        "commit_sha": get_git_commit_short(),
        "livestream_host": settings.LIVESTREAM_HOST,
        "persisted_feature_flags": settings.PERSISTED_FEATURE_FLAGS,
        "anonymous": True,
    }


class SharePasswordSerializer(serializers.ModelSerializer):
    created_by_email = serializers.SerializerMethodField()

    def get_created_by_email(self, obj):
        return obj.created_by.email if obj.created_by else "deleted user"

    class Meta:
        model = SharePassword
        fields = ["id", "created_at", "note", "created_by_email", "is_active"]
        read_only_fields = ["id", "created_at", "created_by_email", "is_active"]


class SharePasswordCreateSerializer(serializers.Serializer):
    raw_password = serializers.CharField(
        required=False, allow_blank=True, help_text="If not provided, a random password will be generated"
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate_raw_password(self, value):
        if value and len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")
        return value


class SharingConfigurationSerializer(serializers.ModelSerializer):
    settings = serializers.JSONField(required=False, allow_null=True)
    share_passwords = serializers.SerializerMethodField()

    class Meta:
        model = SharingConfiguration
        fields = ["created_at", "enabled", "access_token", "settings", "password_required", "share_passwords"]
        read_only_fields = ["created_at", "access_token", "share_passwords"]

    def validate_settings(self, value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if value is None:
            return None
        try:
            # Filter out unknown fields before validation since the schema has extra="forbid"
            known_fields = SharingConfigurationSettings.model_fields.keys()
            filtered_data = {k: v for k, v in value.items() if k in known_fields}

            validated_settings = SharingConfigurationSettings.model_validate(filtered_data, strict=False)
            result = validated_settings.model_dump(exclude_none=True)
            return result
        except Exception as e:
            capture_exception(e)
            raise serializers.ValidationError("Invalid settings format")

    def get_share_passwords(self, obj):
        # Return empty list for unsaved instances to avoid database relationship access
        if not obj.pk:
            return []
        return SharePasswordSerializer(obj.share_passwords.filter(is_active=True), many=True).data


class SharingConfigurationViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "sharing_configuration"
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "refresh",
        "create_password",
        "delete_password",
    ]
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

        if request.data.get("password_required", False):
            if not self.organization.is_feature_available(AvailableFeature.ADVANCED_PERMISSIONS):
                return response.Response(
                    {"error": "Sharing with password requires the Advanced Permissions feature"}, status=403
                )

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

        if context.get("recording"):
            recording = cast(SessionRecording, context.get("recording"))
            # Special case where we need to save the instance for recordings so that the actual record gets created
            recording.save()

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

    @action(detail=False, methods=["post"], url_path="passwords")
    def create_password(self, request: Request, *args: Any, **kwargs: Any) -> response.Response:
        """Create a new password for the sharing configuration."""
        context = self.get_serializer_context()
        sharing_config = self._get_sharing_configuration(context)

        check_can_edit_sharing_configuration(self, request, sharing_config)

        if not sharing_config.password_required:
            return response.Response(
                {"error": "Password protection must be enabled before creating passwords"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not self.organization.is_feature_available(AvailableFeature.ADVANCED_PERMISSIONS):
            return response.Response(
                {"error": "Password management requires the Advanced Permissions feature"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Save the sharing config if it's new
        if not sharing_config.id:
            sharing_config.save()

        serializer = SharePasswordCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        share_password, raw_password = SharePassword.create_password(
            sharing_configuration=sharing_config,
            created_by=cast(User, request.user),
            raw_password=serializer.validated_data.get("raw_password") or None,
            note=serializer.validated_data.get("note", ""),
        )

        return response.Response(
            {
                "id": share_password.id,
                "password": raw_password,  # Only returned once on creation
                "note": share_password.note,
                "created_at": share_password.created_at,
                "created_by_email": share_password.created_by.email if share_password.created_by else "deleted user",
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["delete"], url_path="passwords/(?P<password_id>[^/.]+)")
    def delete_password(self, request: Request, password_id: str, *args: Any, **kwargs: Any) -> response.Response:
        """Delete a password from the sharing configuration."""
        context = self.get_serializer_context()
        sharing_config = self._get_sharing_configuration(context)

        check_can_edit_sharing_configuration(self, request, sharing_config)

        if not self.organization.is_feature_available(AvailableFeature.ADVANCED_PERMISSIONS):
            return response.Response(
                {"error": "Password management requires the Advanced Permissions feature"},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            share_password = sharing_config.share_passwords.get(id=password_id, is_active=True)
            share_password.is_active = False
            share_password.save()
            return response.Response(status=status.HTTP_204_NO_CONTENT)
        except SharePassword.DoesNotExist:
            raise NotFound("Password not found")


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

    # Only use sharing-specific authentication, ignore regular PostHog auth
    authentication_classes = [SharingPasswordProtectedAuthentication, SharingAccessTokenAuthentication]
    permission_classes = []
    serializer_class = SharingConfigurationSerializer  # Required by DRF but not used in practice

    def initial(self, request, *args, **kwargs):
        """Override to ensure we don't apply any session authentication."""
        # Save and clear any existing user to ensure we start fresh
        self._original_user = getattr(request, "user", None)

        # Set user to AnonymousUser before calling super() to ensure throttle checks work
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()

        super().initial(request, *args, **kwargs)

        # If no sharing auth succeeded, ensure user remains anonymous
        if not request.user:
            request.user = AnonymousUser()

    def get_object(self) -> Optional[SharingConfiguration | ExportedAsset]:
        # JWT based access (ExportedAsset)
        token = self.request.query_params.get("token")
        if token:
            try:
                asset = asset_for_token(token)
                if asset:
                    return asset
            except ExportedAsset.DoesNotExist:
                raise NotFound()

        # Path based access (SharingConfiguration only)
        access_token = self.kwargs.get("access_token", "").split(".")[0]
        if access_token:
            try:
                sharing_configuration = (
                    SharingConfiguration.objects.select_related("dashboard", "insight", "recording")
                    .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now()))
                    .get(access_token=access_token)
                )
            except SharingConfiguration.DoesNotExist:
                raise NotFound()

            if sharing_configuration and sharing_configuration.enabled:
                # Additional validation: if user is JWT authenticated, ensure the JWT is for this specific share
                if isinstance(self.request.successful_authenticator, SharingPasswordProtectedAuthentication):
                    jwt_sharing_config = self.request.successful_authenticator.sharing_configuration
                    if jwt_sharing_config.access_token != access_token:
                        # JWT is valid but for a different share - clear authentication to show unlock page
                        self.request._not_authenticated()

                return sharing_configuration

        return None

    def _validate_share_password(
        self, sharing_configuration: SharingConfiguration, raw_password: str
    ) -> Optional[SharePassword]:
        """
        Validate password against SharePassword entries.
        Returns the matching SharePassword if found, None otherwise.
        """
        for share_password in sharing_configuration.share_passwords.filter(is_active=True):
            if share_password.check_password(raw_password):
                return share_password

        return None

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        return self.retrieve(request, *args, **kwargs)

    @xframe_options_exempt
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Any:
        try:
            resource = self.get_object()
        except NotFound:
            resource = None

        if not resource:
            return custom_404_response(self.request)

        # Check if organization allows publicly shared resources
        if (
            isinstance(resource, SharingConfiguration)
            and resource.team.organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)
            and not resource.team.organization.allow_publicly_shared_resources
        ):
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

        available_features = resource.team.organization.available_product_features or []
        if "whitelabel" in request.GET and "white_labelling" in [feature["key"] for feature in available_features]:
            exported_data.update({"whitelabel": True})

        if isinstance(resource, SharingConfiguration) and resource.password_required:
            # Check if user is already authenticated via JWT token (Bearer or cookie)
            is_jwt_authenticated = isinstance(request.successful_authenticator, SharingPasswordProtectedAuthentication)

            if request.method == "GET" and not is_jwt_authenticated:
                exported_data["type"] = "unlock"
                # Don't include app_context in the initial unlock page for security
                # It will be provided after authentication
                return render_template(
                    "exporter.html",
                    request=request,
                    context={
                        "exported_data": json.dumps(exported_data, cls=DjangoJSONEncoder),
                        "add_og_tags": None,
                    },
                )
            elif request.method == "GET" and is_jwt_authenticated:
                # JWT authenticated (via cookie or Bearer) - render full app context

                # Include the JWT token from the cookie so frontend can use it for API calls
                jwt_token = request.COOKIES.get("posthog_sharing_token")
                if jwt_token:
                    exported_data["shareToken"] = jwt_token
                # Continue processing to add dashboard/insight data to exported_data
            elif request.method == "POST":
                validated_password = None
                if "password" in request.data:
                    validated_password = self._validate_share_password(resource, request.data["password"])

                if not validated_password:
                    _log_share_password_attempt(resource, request, success=False)
                    return response.Response({"error": "Incorrect password"}, status=401)

                _log_share_password_attempt(resource, request, success=True, validated_password=validated_password)

                # Password is correct - generate JWT token, set cookie, and return token
                jwt_token = resource.generate_password_protected_token(validated_password)
                response_data = response.Response({"shareToken": jwt_token})
                # Set HTTP-only cookie that expires with the JWT (24 hours)
                # Scope the cookie to this specific share path to avoid conflicts between shares
                # Extract the base path without any file extensions (e.g., "/shared/token.png" -> "/shared/token")
                cookie_path = request.path.split(".")[0]
                response_data.set_cookie(
                    "posthog_sharing_token",
                    jwt_token,
                    max_age=24 * 60 * 60,  # 24 hours in seconds
                    path=cookie_path,
                    httponly=True,
                    secure=request.is_secure(),
                    samesite="Lax",
                )
                return response_data

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

        # Check both query params (legacy) and settings for configuration options
        state = getattr(resource, "settings", {}) or {}

        if resource.insight and not resource.insight.deleted:
            # Both insight AND dashboard can be set. If both it is assumed we should render that
            context["dashboard"] = resource.dashboard
            asset_title = resource.insight.name or resource.insight.derived_name
            asset_description = resource.insight.description or ""
            InsightViewed.objects.update_or_create(
                insight=resource.insight, team=None, user=None, defaults={"last_viewed_at": now()}
            )

            # Add hideExtraDetails to context so that PII related information is not returned to the client
            insight_context = {**context, "hide_extra_details": state.get("hideExtraDetails", False)}
            insight_data = InsightSerializer(resource.insight, many=False, context=insight_context).data
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
            isinstance(resource, ExportedAsset)
            and resource.export_context
            and resource.export_context.get("session_recording_id")
        ):
            # Handle replay export via export_context
            session_recording_id = resource.export_context.get("session_recording_id")
            timestamp = resource.export_context.get("timestamp")

            if not session_recording_id:
                raise NotFound("Invalid replay export - missing session_recording_id")

            # Validate session_recording_id format (UUID-like)
            if not isinstance(session_recording_id, str) or len(session_recording_id) > 200:
                raise NotFound("Invalid session_recording_id format")

            # Validate timestamp is a number if present
            if timestamp is not None:
                try:
                    timestamp = float(timestamp)
                    if timestamp < 0:  # Negative timestamps don't make sense
                        timestamp = 0
                except (ValueError, TypeError):
                    timestamp = 0  # Default to start if invalid

            # Create a SessionRecording object for the replay
            try:
                # First, try to get existing recording from database
                recording, _ = SessionRecording.objects.get_or_create(
                    session_id=session_recording_id, team=resource.team
                )

                # Create a JWT for the recording
                export_access_token = ""
                if resource.created_by and resource.created_by.id:
                    export_access_token = encode_jwt(
                        {"id": resource.created_by.id},
                        timedelta(minutes=5),  # 5 mins should be enough for the export to complete
                        PosthogJwtAudience.IMPERSONATED_USER,
                    )

                asset_title = "Session Recording"
                asset_description = f"Recording {session_recording_id}"

                mode = resource.export_context.get("mode")
                if mode not in ("screenshot", "video"):
                    mode = "screenshot"

                recording_data = SessionRecordingSerializer(recording, context=context).data

                exported_data.update(
                    {
                        "type": "replay_export",
                        "recording": recording_data,
                        "timestamp": timestamp,
                        "session_recording_id": session_recording_id,
                        "exportToken": export_access_token,
                        "noBorder": True,
                        "autoplay": True,
                        "mode": mode,
                    }
                )

            except Exception:
                raise NotFound("No recording found")
        elif (
            isinstance(resource, ExportedAsset)
            and resource.export_context
            and resource.export_context.get("heatmap_url")
        ):
            # Handle heatmap export via export_context
            heatmap_url = resource.export_context.get("heatmap_url")

            if not heatmap_url:
                raise NotFound("Invalid replay export - missing heatmap_url")

            try:
                # Create a JWT to access the heatmap data
                export_access_token = ""
                if resource.created_by and resource.created_by.id:
                    export_access_token = encode_jwt(
                        {"id": resource.created_by.id},
                        timedelta(minutes=5),
                        PosthogJwtAudience.IMPERSONATED_USER,
                    )

                asset_title = "Heatmap"
                asset_description = f"Heatmap {heatmap_url}"

                exported_data.update(
                    {
                        "type": "heatmap",
                        "heatmap_url": heatmap_url,
                        "exportToken": export_access_token,
                        "noBorder": True,
                        "heatmap_context": resource.export_context,
                    }
                )

            except Exception:
                raise NotFound("No heatmap found")
        elif isinstance(resource, SharingConfiguration) and resource.recording and not resource.recording.deleted:
            asset_title = "Session Recording"
            recording_data = SessionRecordingSerializer(resource.recording, context=context).data
            exported_data.update({"recording": recording_data})
        else:
            raise NotFound("No resource found")

        # Get sharing settings using Pydantic model for validation and defaults
        settings_data = getattr(resource, "settings", {}) or {}
        base_settings = SharingConfigurationSettings.model_validate(settings_data, strict=False)

        # Only check query params for configurations created before SETTINGS_SHIP_DATE
        SETTINGS_SHIP_DATE = "2025-07-31"
        created_before_settings_ship = False
        if isinstance(resource, SharingConfiguration):
            created_before_settings_ship = resource.created_at.strftime("%Y-%m-%d") < SETTINGS_SHIP_DATE

        # Exported assets don't have settings so we can continue to use query params
        can_use_query_params = created_before_settings_ship or not isinstance(resource, SharingConfiguration)

        # Merge query params with base settings if allowed
        if can_use_query_params:
            # Convert query params to dict and merge with base settings
            merged_data = base_settings.model_dump()
            for field_name in base_settings.model_fields.keys():
                if field_name in request.GET:
                    merged_data[field_name] = bool(request.GET[field_name])
            final_settings = SharingConfigurationSettings.model_validate(merged_data, strict=False)
        else:
            final_settings = base_settings

        # Apply settings to exported data
        if final_settings.whitelabel and resource.team.organization.is_feature_available(
            AvailableFeature.WHITE_LABELLING
        ):
            exported_data.update({"whitelabel": True})

        if final_settings.noHeader:
            exported_data.update({"noHeader": True})
        if final_settings.showInspector:
            exported_data.update({"showInspector": True})
        if final_settings.legend:
            exported_data.update({"legend": True})
        if final_settings.detailed:
            exported_data.update({"detailed": True})
        if final_settings.hideExtraDetails:
            exported_data.update({"hideExtraDetails": True})

        if request.path.endswith(f".json"):
            # For password-protected POST requests, only return basic metadata and JWT token
            if request.method == "POST" and isinstance(resource, SharingConfiguration) and resource.password_required:
                # Return only the essentials for the frontend to work
                minimal_data = {
                    "type": exported_data.get("type", "scene"),
                    "shareToken": exported_data.get("shareToken"),
                    "whitelabel": exported_data.get("whitelabel", False),
                    "noHeader": exported_data.get("noHeader", False),
                    "showInspector": exported_data.get("showInspector", False),
                    "legend": exported_data.get("legend", False),
                    "detailed": exported_data.get("detailed", False),
                }
                return response.Response(minimal_data)
            return response.Response(exported_data)

        if request.GET.get("force_type"):
            exported_data["type"] = request.GET.get("force_type")

        exported_data["rootClassName"] = f"export-type-'{exported_data.get('type', 'unknown')}"
        # Check if this is a JWT authenticated request with JSON Accept header
        if (
            isinstance(resource, SharingConfiguration)
            and resource.password_required
            and isinstance(request.successful_authenticator, SharingPasswordProtectedAuthentication)
            and request.headers.get("Accept") == "application/json"
        ):
            # Return dashboard data as JSON for XHR requests
            return response.Response(exported_data)

        context = {
            "exported_data": json.dumps(exported_data, cls=DjangoJSONEncoder),
            "asset_title": asset_title,
            "asset_description": asset_description,
            "add_og_tags": add_og_tags,
            "asset_opengraph_image_url": shared_url_as_png(request.build_absolute_uri()),
        }

        return render_template(
            "exporter.html",
            request=request,
            context=context,
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
