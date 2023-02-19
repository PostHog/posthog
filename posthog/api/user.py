import json
import os
import secrets
import urllib.parse
from typing import Any, Optional, cast

import posthoganalytics
import requests
from django.conf import settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_filters.rest_framework import DjangoFilterBackend
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, mixins, permissions, serializers, viewsets
from rest_framework.throttling import UserRateThrottle

from posthog.api.organization import OrganizationSerializer
from posthog.api.shared import OrganizationBasicSerializer, TeamBasicSerializer
from posthog.auth import authenticate_secondarily
from posthog.cloud_utils import is_cloud
from posthog.email import is_email_available
from posthog.event_usage import report_user_updated
from posthog.models import Team, User
from posthog.models.organization import Organization
from posthog.models.user import NOTIFICATION_DEFAULTS, Notifications
from posthog.tasks import user_identify
from posthog.tasks.email import send_email_change_emails, send_email_verification
from posthog.user_permissions import UserPermissions
from posthog.utils import get_js_url


class UserAuthenticationThrottle(UserRateThrottle):
    rate = "5/minute"

    def allow_request(self, request, view):
        # only throttle non-GET requests
        if request.method == "GET":
            return True
        return super().allow_request(request, view)


class UserSerializer(serializers.ModelSerializer):

    has_password = serializers.SerializerMethodField()
    is_impersonated = serializers.SerializerMethodField()
    team = TeamBasicSerializer(read_only=True)
    organization = OrganizationSerializer(read_only=True)
    organizations = OrganizationBasicSerializer(many=True, read_only=True)
    set_current_organization = serializers.CharField(write_only=True, required=False)
    set_current_team = serializers.CharField(write_only=True, required=False)
    current_password = serializers.CharField(write_only=True, required=False)
    notification_settings = serializers.DictField(required=False)

    class Meta:
        model = User
        fields = [
            "date_joined",
            "uuid",
            "distinct_id",
            "first_name",
            "email",
            "pending_email",
            "email_opt_in",
            "is_email_verified",
            "pending_email",
            "notification_settings",
            "anonymize_data",
            "toolbar_mode",
            "has_password",
            "is_staff",
            "is_impersonated",
            "team",
            "organization",
            "organizations",
            "set_current_organization",
            "set_current_team",
            "password",
            "current_password",  # used when changing current password
            "events_column_config",
        ]
        extra_kwargs = {"date_joined": {"read_only": True}, "password": {"write_only": True}}

    def get_has_password(self, instance: User) -> bool:
        return instance.has_usable_password()

    def get_is_impersonated(self, _) -> Optional[bool]:
        if "request" not in self.context:
            return None
        return is_impersonated_session(self.context["request"])

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
        for key, value in notification_settings.items():
            if key not in Notifications.__annotations__:
                raise serializers.ValidationError(f"Key {key} is not valid as a key for notification settings")

            if not isinstance(value, Notifications.__annotations__[key]):
                raise serializers.ValidationError(
                    f"{value} is not a valid type for notification settings, should be {Notifications.__annotations__[key]}"
                )
        return {**NOTIFICATION_DEFAULTS, **notification_settings}  # type: ignore

    def validate_password_change(
        self, instance: User, current_password: Optional[str], password: Optional[str]
    ) -> Optional[str]:
        if password:
            if instance.password and instance.has_usable_password():
                # If user has a password set, we check it's provided to allow updating it. We need to check that is both
                # usable (properly hashed) and that a password actually exists.
                if not current_password:
                    raise serializers.ValidationError(
                        {"current_password": ["This field is required when updating your password."]}, code="required"
                    )

                if not instance.check_password(current_password):
                    raise serializers.ValidationError(
                        {"current_password": ["Your current password is incorrect."]}, code="incorrect_password"
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

        require_verification_feature = (
            posthoganalytics.feature_enabled("require-email-verification", str(instance.distinct_id)) and is_cloud()
        )

        if (
            "email" in validated_data
            and validated_data["email"].lower() != instance.email.lower()
            and is_email_available()
        ):
            if require_verification_feature:
                # Verification tokens remain valid until the user logs in again. So in order to invalidate existing tokens
                # we need to log the user in first, and then generate a new token. This prevents people
                # from generating a token for an email they have access to, then changing the email to one they don't
                # and using the first token to verify the second email.
                login(self.context["request"], instance, backend="django.contrib.auth.backends.ModelBackend")
                instance.pending_email = validated_data.pop("email", None)
                instance.save()
                send_email_verification.delay(instance.id)
            else:
                send_email_change_emails.delay(
                    timezone.now().isoformat(), instance.first_name, instance.email, validated_data["email"]
                )

        # Update password
        current_password = validated_data.pop("current_password", None)
        password = self.validate_password_change(
            cast(User, instance), current_password, validated_data.pop("password", None)
        )

        if validated_data.get("notification_settings"):
            validated_data["partial_notification_settings"] = validated_data.pop("notification_settings")

        updated_attrs = list(validated_data.keys())
        instance = cast(User, super().update(instance, validated_data))

        if password:
            instance.set_password(password)
            instance.save()
            update_session_auth_hash(self.context["request"], instance)
            updated_attrs.append("password")

        report_user_updated(instance, updated_attrs)

        return instance

    def to_representation(self, instance: Any) -> Any:
        user_identify.identify_task.delay(user_id=instance.id)
        return super().to_representation(instance)


class UserViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    throttle_classes = [UserAuthenticationThrottle]
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_staff"]
    queryset = User.objects.filter(is_active=True)
    lookup_field = "uuid"

    def get_object(self) -> User:
        lookup_value = self.kwargs[self.lookup_field]
        request_user = cast(User, self.request.user)  # Must be authenticated to access this endpoint
        if lookup_value == "@me":
            return request_user

        if not request_user.is_staff:
            raise exceptions.PermissionDenied(
                "As a non-staff user you're only allowed to access the `@me` user instance."
            )

        return super().get_object()

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(id=self.request.user.id)
        return queryset

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "user_permissions": UserPermissions(cast(User, self.request.user))}


@authenticate_secondarily
def redirect_to_site(request):
    team = request.user.team
    app_url = request.GET.get("appUrl") or (team.app_urls and team.app_urls[0])
    use_new_toolbar = request.user.toolbar_mode != "disabled"

    if not app_url:
        return HttpResponse(status=404)

    request.user.temporary_token = secrets.token_urlsafe(32)
    request.user.save()
    params = {
        "action": "ph_authorize",
        "token": team.api_token,
        "temporaryToken": request.user.temporary_token,
        "actionId": request.GET.get("actionId"),
        "userIntent": request.GET.get("userIntent"),
        "toolbarVersion": "toolbar",
        "apiURL": request.build_absolute_uri("/")[:-1],
        "dataAttributes": team.data_attributes,
    }

    if get_js_url(request):
        params["jsURL"] = get_js_url(request)

    if not settings.TEST and not os.environ.get("OPT_OUT_CAPTURE"):
        params["instrument"] = True
        params["userEmail"] = request.user.email
        params["distinctId"] = request.user.distinct_id

    # pass the empty string as the safe param so that `//` is encoded correctly.
    # see https://github.com/PostHog/posthog/issues/9671
    state = urllib.parse.quote(json.dumps(params), safe="")

    if use_new_toolbar:
        return redirect("{}#__posthog={}".format(app_url, state))
    else:
        return redirect("{}#state={}".format(app_url, state))


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
        response = requests.post(webhook, verify=False, json=message)

        if response.ok:
            return JsonResponse({"success": True})
        else:
            return JsonResponse({"error": response.text})
    except:
        return JsonResponse({"error": "invalid webhook URL"})
