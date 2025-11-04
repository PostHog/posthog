import os
import json
import time
import secrets
import urllib.parse
from base64 import b32encode
from binascii import unhexlify
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from django.conf import settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods

import jwt
import requests
import structlog
from django_filters.rest_framework import DjangoFilterBackend
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.util import random_hex
from loginas.utils import is_impersonated_session
from prometheus_client import Counter
from rest_framework import exceptions, mixins, serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from two_factor.forms import TOTPDeviceForm
from two_factor.utils import default_device

from posthog.api.email_verification import EmailVerifier
from posthog.api.organization import OrganizationSerializer
from posthog.api.shared import OrganizationBasicSerializer, TeamBasicSerializer
from posthog.api.utils import (
    ClassicBehaviorBooleanFieldSerializer,
    PublicIPOnlyHttpAdapter,
    action,
    raise_if_user_provided_url_unsafe,
    unparsed_hostname_in_allowed_url_list,
)
from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    TemporaryTokenAuthentication,
    authenticate_secondarily,
)
from posthog.constants import PERMITTED_FORUM_DOMAINS
from posthog.email import is_email_available
from posthog.event_usage import (
    report_user_deleted_account,
    report_user_logged_in,
    report_user_updated,
    report_user_verified_email,
)
from posthog.helpers.session_cache import SessionCache
from posthog.helpers.two_factor_session import set_two_factor_verified_in_session
from posthog.middleware import get_impersonated_session_expires_at
from posthog.models import Dashboard, Team, User, UserPinnedSceneTabs, UserScenePersonalisation
from posthog.models.organization import Organization
from posthog.models.user import NOTIFICATION_DEFAULTS, ROLE_CHOICES, Notifications
from posthog.permissions import APIScopePermission, TimeSensitiveActionPermission, UserNoOrgMembershipDeletePermission
from posthog.rate_limit import UserAuthenticationThrottle, UserEmailVerificationThrottle
from posthog.tasks import user_identify
from posthog.tasks.email import (
    send_email_change_emails,
    send_password_changed_email,
    send_two_factor_auth_disabled_email,
    send_two_factor_auth_enabled_email,
)
from posthog.user_permissions import UserPermissions

REDIRECT_TO_SITE_COUNTER = Counter("posthog_redirect_to_site", "Redirect to site")
REDIRECT_TO_SITE_FAILED_COUNTER = Counter("posthog_redirect_to_site_failed", "Redirect to site failed")

logger = structlog.get_logger(__name__)


class ScenePersonalisationBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserScenePersonalisation
        fields = ["scene", "dashboard"]


class UserSerializer(serializers.ModelSerializer):
    has_password = serializers.SerializerMethodField()
    is_impersonated = serializers.SerializerMethodField()
    is_impersonated_until = serializers.SerializerMethodField()
    sensitive_session_expires_at = serializers.SerializerMethodField()
    is_2fa_enabled = serializers.SerializerMethodField()
    has_social_auth = serializers.SerializerMethodField()
    has_sso_enforcement = serializers.SerializerMethodField()
    team = TeamBasicSerializer(read_only=True)
    organization = OrganizationSerializer(read_only=True)
    organizations = OrganizationBasicSerializer(many=True, read_only=True)
    set_current_organization = serializers.CharField(write_only=True, required=False)
    set_current_team = serializers.CharField(write_only=True, required=False)
    current_password = serializers.CharField(write_only=True, required=False)
    notification_settings = serializers.DictField(required=False)
    scene_personalisation = ScenePersonalisationBasicSerializer(many=True, read_only=True)
    anonymize_data = ClassicBehaviorBooleanFieldSerializer()
    role_at_organization = serializers.ChoiceField(choices=ROLE_CHOICES, required=False)

    class Meta:
        model = User
        fields = [
            "date_joined",
            "uuid",
            "distinct_id",
            "first_name",
            "last_name",
            "email",
            "pending_email",
            "is_email_verified",
            "notification_settings",
            "anonymize_data",
            "toolbar_mode",
            "has_password",
            "id",
            "is_staff",
            "is_impersonated",
            "is_impersonated_until",
            "sensitive_session_expires_at",
            "team",
            "organization",
            "organizations",
            "set_current_organization",
            "set_current_team",
            "password",
            "current_password",  # used when changing current password
            "events_column_config",
            "is_2fa_enabled",
            "has_social_auth",
            "has_sso_enforcement",
            "has_seen_product_intro_for",
            "scene_personalisation",
            "theme_mode",
            "hedgehog_config",
            "role_at_organization",
        ]

        read_only_fields = [
            "date_joined",
            "uuid",
            "distinct_id",
            "pending_email",
            "is_email_verified",
            "has_password",
            "id",
            "is_impersonated",
            "is_impersonated_until",
            "sensitive_session_expires_at",
            "team",
            "organization",
            "organizations",
            "has_social_auth",
            "has_sso_enforcement",
        ]

        extra_kwargs = {
            "password": {"write_only": True},
        }

    def get_has_password(self, instance: User) -> bool:
        return bool(instance.password) and instance.has_usable_password()

    def get_is_impersonated(self, _) -> Optional[bool]:
        if "request" not in self.context:
            return None
        return is_impersonated_session(self.context["request"])

    def get_is_impersonated_until(self, _) -> Optional[str]:
        if "request" not in self.context or not is_impersonated_session(self.context["request"]):
            return None

        expires_at_time = get_impersonated_session_expires_at(self.context["request"])

        return expires_at_time.replace(tzinfo=UTC).isoformat() if expires_at_time else None

    def get_sensitive_session_expires_at(self, instance: User) -> Optional[str]:
        if "request" not in self.context:
            return None

        session_created_at: int = self.context["request"].session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)

        if not session_created_at:
            # This should always be covered by the middleware but just in case
            return None

        # Session expiry is the time when the session was created plus the
        session_expiry_time = datetime.fromtimestamp(session_created_at) + timedelta(
            seconds=settings.SESSION_SENSITIVE_ACTIONS_AGE
        )

        return session_expiry_time.replace(tzinfo=UTC).isoformat()

    def get_has_social_auth(self, instance: User) -> bool:
        return instance.social_auth.exists()

    def get_is_2fa_enabled(self, instance: User) -> bool:
        return default_device(instance) is not None

    def get_has_sso_enforcement(self, instance: User) -> bool:
        from posthog.models.organization_domain import OrganizationDomain

        organization = instance.current_organization
        if not organization:
            return False

        return bool(
            OrganizationDomain.objects.get_sso_enforcement_for_email_address(instance.email, organization=organization)
        )

    def validate_set_current_organization(self, value: str) -> Organization:
        try:
            organization = Organization.objects.get(id=value)
            if organization.memberships.filter(user=self.context["request"].user).exists():
                return organization
        except Organization.DoesNotExist:
            pass

        raise serializers.ValidationError(f"Object with id={value} does not exist.", code="does_not_exist")

    def validate_set_current_team(self, value: str) -> Team:
        try:
            team = Team.objects.get(pk=value)
            if self.context["request"].user.teams.filter(pk=team.pk).exists():
                return team
        except Team.DoesNotExist:
            pass

        raise serializers.ValidationError(f"Object with id={value} does not exist.", code="does_not_exist")

    def validate_notification_settings(self, notification_settings: Notifications) -> Notifications:
        instance = cast(User, self.instance)
        current_settings = {**NOTIFICATION_DEFAULTS, **(instance.partial_notification_settings or {})}

        for key, value in notification_settings.items():
            if key not in Notifications.__annotations__:
                raise serializers.ValidationError(
                    f"Key {key} is not valid as a key for notification settings", code="invalid_input"
                )

            expected_type = Notifications.__annotations__[key]

            if key == "project_weekly_digest_disabled":
                if not isinstance(value, dict):
                    raise serializers.ValidationError(
                        f"project_weekly_digest_disabled must be a dictionary mapping project IDs to boolean values",
                        code="invalid_input",
                    )
                # Validate each project setting is a boolean
                for _, disabled in value.items():
                    if not isinstance(disabled, bool):
                        raise serializers.ValidationError(
                            f"Project notification setting values must be boolean, got {type(disabled)} instead",
                            code="invalid_input",
                        )
                # Merge with existing settings
                current_settings[key] = {**current_settings.get("project_weekly_digest_disabled", {}), **value}
            else:
                # For non-dict settings, validate type directly
                if not isinstance(value, expected_type):
                    raise serializers.ValidationError(
                        f"{value} is not a valid type for notification settings, should be {expected_type}",
                        code="invalid_input",
                    )
                current_settings[key] = value

        return cast(Notifications, current_settings)

    def validate_password_change(
        self, instance: User, current_password: Optional[str], password: Optional[str]
    ) -> Optional[str]:
        if password:
            if instance.password and instance.has_usable_password():
                # If user has a password set, we check it's provided to allow updating it. We need to check that is both
                # usable (properly hashed) and that a password actually exists.
                if not current_password:
                    raise serializers.ValidationError(
                        {"current_password": ["This field is required when updating your password."]},
                        code="required",
                    )

                if not instance.check_password(current_password):
                    raise serializers.ValidationError(
                        {"current_password": ["Your current password is incorrect."]},
                        code="incorrect_password",
                    )
            try:
                validate_password(password, instance)
            except ValidationError as e:
                raise serializers.ValidationError({"password": e.messages})

        return password

    def validate_is_staff(self, value: bool) -> bool:
        if not self.context["request"].user.is_staff:
            raise exceptions.PermissionDenied("You are not a staff user, contact your instance admin.")
        return value

    def validate_role_at_organization(self, value):
        if value and value not in dict(ROLE_CHOICES):
            raise serializers.ValidationError("Invalid role selected")
        return value

    def update(self, instance: "User", validated_data: Any) -> Any:
        # Update current_organization and current_team
        current_organization = validated_data.pop("set_current_organization", None)
        current_team = validated_data.pop("set_current_team", None)
        if current_organization:
            if current_team and not current_organization.teams.filter(pk=current_team.pk).exists():
                raise serializers.ValidationError(
                    {"set_current_team": ["Team must belong to the same organization in set_current_organization."]}
                )

            validated_data["current_organization"] = current_organization
            validated_data["current_team"] = current_team if current_team else current_organization.teams.first()
        elif current_team:
            validated_data["current_team"] = current_team
            validated_data["current_organization"] = current_team.organization

        if (
            "email" in validated_data
            and validated_data["email"].lower() != instance.email.lower()
            and is_email_available()
        ):
            instance.pending_email = validated_data.pop("email", None)
            instance.save()
            EmailVerifier.create_token_and_send_email_verification(instance)

        if validated_data.get("notification_settings"):
            validated_data["partial_notification_settings"] = validated_data.pop("notification_settings")

        # Update password
        current_password = validated_data.pop("current_password", None)
        password = self.validate_password_change(
            cast(User, instance), current_password, validated_data.pop("password", None)
        )

        updated_attrs = list(validated_data.keys())
        instance = cast(User, super().update(instance, validated_data))

        if password:
            instance.set_password(password)
            instance.save()
            update_session_auth_hash(self.context["request"], instance)
            updated_attrs.append("password")
            send_password_changed_email.delay(instance.id)

        report_user_updated(instance, updated_attrs)

        return instance

    def to_representation(self, instance: Any) -> Any:
        user_identify.identify_task.delay(user_id=instance.id)
        return super().to_representation(instance)


class ScenePersonalisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserScenePersonalisation
        fields = ["scene", "dashboard"]
        read_only_fields = ["user", "team"]

    def validate_dashboard(self, value: Dashboard) -> Dashboard:
        instance = cast(User, self.instance)

        if value.team != instance.current_team:
            raise serializers.ValidationError("Dashboard must belong to the user's current team.")

        return value

    def validate(self, data):
        if "dashboard" not in data:
            raise serializers.ValidationError("Dashboard must be provided.")

        if "scene" not in data:
            raise serializers.ValidationError("Scene must be provided.")

        return data

    def save(self, **kwargs):
        instance = cast(User, self.instance)
        if not instance:
            # there must always be a user instance
            raise NotFound()

        validated_data = {**self.validated_data, **kwargs}

        return UserScenePersonalisation.objects.update_or_create(
            user=instance,
            team=instance.current_team,
            scene=validated_data["scene"],
            defaults={"dashboard": validated_data["dashboard"]},
        )


class PinnedSceneTabSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True)
    pathname = serializers.CharField()
    search = serializers.CharField()
    hash = serializers.CharField()
    title = serializers.CharField()
    customTitle = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    iconType = serializers.CharField()
    sceneId = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    sceneKey = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    sceneParams = serializers.JSONField(required=False)
    pinned = serializers.BooleanField(required=False)


class PinnedSceneTabsSerializer(serializers.Serializer):
    tabs = PinnedSceneTabSerializer(many=True)


class UserViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "user"
    throttle_classes = [UserAuthenticationThrottle]
    serializer_class = UserSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        UserNoOrgMembershipDeletePermission,
        TimeSensitiveActionPermission,
    ]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_staff", "email"]
    queryset = User.objects.filter(is_active=True)
    lookup_field = "uuid"

    def get_object(self) -> User:
        lookup_value = self.kwargs[self.lookup_field]
        request_user = cast(User, self.request.user)  # Must be authenticated to access this endpoint
        if lookup_value == "@me":
            self.check_object_permissions(self.request, request_user)
            return request_user

        if not request_user.is_staff:
            raise exceptions.PermissionDenied(
                "As a non-staff user you're only allowed to access the `@me` user instance."
            )

        return super().get_object()

    def get_authenticators(self):
        if self.request and self.request.method == "DELETE":  # Do not support deleting own user account via the API
            return [SessionAuthentication()]

        return super().get_authenticators()

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(id=self.request.user.id)
        return queryset

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "user_permissions": UserPermissions(cast(User, self.request.user)),
        }

    def perform_destroy(self, user: User) -> None:
        report_user_deleted_account(user)
        super().perform_destroy(user)

    @action(methods=["POST"], detail=False, permission_classes=[AllowAny])
    def verify_email(self, request, **kwargs):
        token = request.data["token"] if "token" in request.data else None
        user_uuid = request.data["uuid"]

        if not token:
            raise serializers.ValidationError({"token": ["This field is required."]}, code="required")

        # Special handling for E2E tests
        if settings.E2E_TESTING and user_uuid == "e2e_test_user" and token == "e2e_test_token":
            return {"success": True, "token": token}

        try:
            user: Optional[User] = User.objects.filter(is_active=True).get(uuid=user_uuid)
        except User.DoesNotExist:
            user = None

        if not user or not EmailVerifier.check_token(user, token):
            raise serializers.ValidationError(
                {"token": ["This verification token is invalid or has expired."]},
                code="invalid_token",
            )

        if user.pending_email:
            old_email = user.email
            user.email = user.pending_email
            user.pending_email = None
            user.save()
            send_email_change_emails.delay(timezone.now().isoformat(), user.first_name, old_email, user.email)

        user.is_email_verified = True
        user.save()
        report_user_verified_email(user)

        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        report_user_logged_in(user)
        return Response({"success": True, "token": token})

    @action(
        methods=["POST"],
        detail=False,
        permission_classes=[AllowAny],
        throttle_classes=[UserEmailVerificationThrottle],
    )
    def request_email_verification(self, request, **kwargs):
        uuid = request.data["uuid"]
        if not is_email_available():
            raise serializers.ValidationError(
                "Cannot verify email address because email is not configured for your instance. Please contact your administrator.",
                code="email_not_available",
            )
        try:
            user = User.objects.filter(is_active=True).get(uuid=uuid)
        except User.DoesNotExist:
            user = None
        if user:
            EmailVerifier.create_token_and_send_email_verification(user)

        return Response({"success": True})

    @action(
        methods=["PATCH"],
        detail=False,
    )
    def cancel_email_change_request(self, request, **kwargs):
        instance = request.user

        if not instance.pending_email:
            raise serializers.ValidationError(
                "No active email change requests found.", code="email_change_request_not_found"
            )

        instance.pending_email = None
        instance.save()

        return Response(self.get_serializer(instance=instance).data)

    @action(methods=["GET", "PATCH"], detail=True)
    def pinned_scene_tabs(self, request, **kwargs):
        instance = self.get_object()
        team = instance.current_team
        if not team:
            raise serializers.ValidationError("Current team is required to manage pinned scene tabs.")

        pinned_tabs, _ = UserPinnedSceneTabs.objects.get_or_create(user=instance, team=team)

        if request.method == "GET":
            return Response({"tabs": pinned_tabs.tabs or []})

        serializer = PinnedSceneTabsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tabs = []
        for tab in serializer.validated_data["tabs"]:
            sanitized = {**tab}
            sanitized.pop("active", None)
            sanitized["pinned"] = True
            tabs.append(sanitized)

        pinned_tabs.tabs = tabs
        pinned_tabs.save()

        return Response({"tabs": pinned_tabs.tabs})

    @action(methods=["POST"], detail=True)
    def scene_personalisation(self, request, **kwargs):
        instance = self.get_object()
        request_serializer = ScenePersonalisationSerializer(instance=instance, data=request.data, partial=True)
        request_serializer.is_valid(raise_exception=True)

        request_serializer.save()
        instance.refresh_from_db()

        return Response(self.get_serializer(instance=instance).data)

    @action(
        methods=["GET", "PATCH"],
        detail=True,
        throttle_classes=[],
        authentication_classes=[
            TemporaryTokenAuthentication,
            SessionAuthentication,
            PersonalAPIKeyAuthentication,
            OAuthAccessTokenAuthentication,
        ],
    )
    def hedgehog_config(self, request, **kwargs):
        instance = self.get_object()
        if request.method == "GET":
            return Response(instance.hedgehog_config or {})
        else:
            instance.hedgehog_config = request.data
            instance.save()
            return Response(instance.hedgehog_config)

    # Deprecated - use two_factor_start_setup instead
    @action(methods=["GET"], detail=True)
    def start_2fa_setup(self, request, **kwargs):
        return self.two_factor_start_setup(request, **kwargs)

    @action(methods=["GET"], detail=True)
    def two_factor_start_setup(self, request, **kwargs):
        key = random_hex(20)
        rawkey = unhexlify(key.encode("ascii"))
        b32key = b32encode(rawkey).decode("utf-8")

        # Concurrent requests can overwrite session saves, breaking the 2FA setup flow, but cache is atomic
        session_cache = SessionCache(request.session)

        # Store for 10 minutes (same as django-two-factor-auth setup flow)
        session_cache.set("django_two_factor-hex", key, timeout=600, store_in_session=True)
        session_cache.set("django_two_factor-qr_secret_key", b32key, timeout=600, store_in_session=True)

        # Return the secret key so the frontend can generate QR code and show it for manual entry
        return Response(
            {
                "success": True,
                "secret": b32key,
            }
        )

    # Deprecated - use two_factor_validate instead
    @action(methods=["POST"], detail=True)
    def validate_2fa(self, request, **kwargs):
        return self.two_factor_validate(request, **kwargs)

    @action(methods=["POST"], detail=True)
    def two_factor_validate(self, request, **kwargs):
        session_cache = SessionCache(request.session)
        hex_key = session_cache.get("django_two_factor-hex")

        if not hex_key:
            raise serializers.ValidationError(
                "2FA setup session expired. Please start setup again.", code="setup_expired"
            )

        form = TOTPDeviceForm(
            hex_key,
            request.user,
            data={"token": request.data["token"]},
        )
        if not form.is_valid():
            raise serializers.ValidationError("Token is not valid", code="token_invalid")
        form.save()
        otp_login(request, default_device(request.user))
        set_two_factor_verified_in_session(request)

        send_two_factor_auth_enabled_email.delay(request.user.id)

        session_cache.delete("django_two_factor-hex")
        session_cache.delete("django_two_factor-qr_secret_key")

        return Response({"success": True})

    @action(methods=["GET"], detail=True)
    def two_factor_status(self, request, **kwargs):
        """Get current 2FA status including backup codes if enabled"""
        user = self.get_object()
        totp_device = TOTPDevice.objects.filter(user=user).first()
        static_device = StaticDevice.objects.filter(user=user).first()

        backup_codes = []
        if static_device:
            backup_codes = [token.token for token in static_device.token_set.all()]

        return Response(
            {
                "is_enabled": default_device(user) is not None,
                "backup_codes": backup_codes if totp_device else [],
                "method": "TOTP" if totp_device else None,
            }
        )

    @action(methods=["POST"], detail=True)
    def two_factor_backup_codes(self, request, **kwargs):
        """Generate new backup codes, invalidating any existing ones"""
        user = self.get_object()

        # Ensure user has 2FA enabled
        if not default_device(user):
            raise serializers.ValidationError("2FA must be enabled first", code="2fa_not_enabled")

        # Remove existing backup codes
        static_device = StaticDevice.objects.filter(user=user).first()
        if static_device:
            static_device.token_set.all().delete()
        else:
            static_device = StaticDevice.objects.create(user=user, name="Backup Codes")

        # Generate new backup codes
        backup_codes = []
        for _ in range(5):  # Generate 5 backup codes
            token = StaticToken.random_token()
            static_device.token_set.create(token=token)
            backup_codes.append(token)

        return Response({"backup_codes": backup_codes})

    @action(methods=["POST"], detail=True)
    def two_factor_disable(self, request, **kwargs):
        """Disable 2FA and remove all related devices"""
        user = self.get_object()

        # Remove all 2FA devices
        TOTPDevice.objects.filter(user=user).delete()
        StaticDevice.objects.filter(user=user).delete()

        send_two_factor_auth_disabled_email.delay(user.id)

        return Response({"success": True})


@authenticate_secondarily
def redirect_to_site(request):
    REDIRECT_TO_SITE_COUNTER.inc()
    team = request.user.team
    app_url = request.GET.get("appUrl") or (team.app_urls and team.app_urls[0])

    if not app_url:
        return HttpResponse(status=404)

    if not team or not unparsed_hostname_in_allowed_url_list(team.app_urls, app_url):
        REDIRECT_TO_SITE_FAILED_COUNTER.inc()
        logger.error(
            "can_only_redirect_to_permitted_domain", permitted_domains=team.app_urls, app_url=app_url, team_id=team.id
        )
        return HttpResponse(f"Can only redirect to a permitted domain.", status=403)
    request.user.temporary_token = secrets.token_urlsafe(32)
    request.user.save()
    params = {
        "action": "ph_authorize",
        "token": team.api_token,
        "temporaryToken": request.user.temporary_token,
        "actionId": request.GET.get("actionId"),
        "experimentId": request.GET.get("experimentId"),
        "userIntent": request.GET.get("userIntent"),
        "toolbarVersion": "toolbar",
        "apiURL": request.build_absolute_uri("/")[:-1],
        "dataAttributes": team.data_attributes,
    }

    if not settings.TEST and not os.environ.get("OPT_OUT_CAPTURE"):
        params["instrument"] = True
        params["userEmail"] = request.user.email
        params["distinctId"] = request.user.distinct_id

    # pass the empty string as the safe param so that `//` is encoded correctly.
    # see https://github.com/PostHog/posthog/issues/9671
    state = urllib.parse.quote(json.dumps(params), safe="")

    if str(request.GET.get("generateOnly")) in ["1", "yes", "true"]:
        return JsonResponse({"toolbarParams": state})
    else:
        return redirect("{}#__posthog={}".format(app_url, state))


@authenticate_secondarily
def redirect_to_website(request):
    team = request.user.team
    app_url = request.GET.get("appUrl") or (team.app_urls and team.app_urls[0])

    if not app_url:
        return HttpResponse(status=404)

    if not team or urllib.parse.urlparse(app_url).hostname not in PERMITTED_FORUM_DOMAINS:
        logger.error(
            "can_only_redirect_to_permitted_domain", permitted_domains=team.app_urls, app_url=app_url, team_id=team.id
        )
        return HttpResponse(f"Can only redirect to a permitted domain.", status=403)

    token = ""

    # check if a strapi id is attached
    if request.user.strapi_id is None:
        response = requests.request(
            "POST",
            "https://squeak.posthog.cc/api/auth/local/register",
            json={
                "username": request.user.email,
                "email": request.user.email,
                "password": secrets.token_hex(32),
                "firstName": request.user.first_name,
                "lastName": request.user.last_name,
            },
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            json_data = response.json()
            token = json_data["jwt"]
            strapi_id = json_data["user"]["id"]
            request.user.strapi_id = strapi_id
            request.user.save()
        else:
            error_message = response.json()["error"]["message"]
            if response.text and error_message == "Email or Username are already taken":
                return redirect("https://posthog.com/auth?error=emailIsTaken")
    else:
        token = jwt.encode(
            {
                "id": request.user.strapi_id,
                "iat": int(time.time()),
                "exp": int((datetime.now() + timedelta(days=30)).timestamp()),
            },
            os.environ.get("JWT_SECRET_STRAPI", "random_fallback_secret"),
            algorithm="HS256",
        )

    # pass the empty string as the safe param so that `//` is encoded correctly.
    # see https://github.com/PostHog/posthog/issues/9671
    userData = urllib.parse.quote(json.dumps({"jwt": token}), safe="")

    return redirect("{}?userData={}&redirect={}".format("https://posthog.com/auth", userData, app_url))


@require_http_methods(["POST"])
@authenticate_secondarily
def test_slack_webhook(request):
    """Test webhook."""
    try:
        body = json.loads(request.body)
    except (TypeError, json.decoder.JSONDecodeError):
        return JsonResponse({"error": "Cannot parse request body"}, status=400)

    webhook = body.get("webhook")

    if not webhook:
        return JsonResponse({"error": "no webhook URL"})
    message = {"text": "_Greetings_ from PostHog!"}
    try:
        session = requests.Session()

        if not settings.DEBUG:
            raise_if_user_provided_url_unsafe(webhook)
            session.mount("https://", PublicIPOnlyHttpAdapter())
            session.mount("http://", PublicIPOnlyHttpAdapter())

        response = session.post(webhook, verify=False, json=message)

        if response.ok:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"error": response.text})
    except:
        return JsonResponse({"error": "invalid webhook URL"})
