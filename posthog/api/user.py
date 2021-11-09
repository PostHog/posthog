import json
import os
import secrets
import urllib.parse
from typing import Any, Optional, cast

import requests
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods
from loginas.utils import is_impersonated_session
from rest_framework import mixins, permissions, serializers, viewsets

from posthog.api.organization import OrganizationSerializer
from posthog.api.shared import OrganizationBasicSerializer, TeamBasicSerializer
from posthog.auth import authenticate_secondarily
from posthog.event_usage import report_user_updated
from posthog.models import Team, User
from posthog.models.organization import Organization
from posthog.tasks import user_identify


class UserSerializer(serializers.ModelSerializer):

    has_password = serializers.SerializerMethodField()
    is_impersonated = serializers.SerializerMethodField()
    team = TeamBasicSerializer(read_only=True)
    organization = OrganizationSerializer(read_only=True)
    organizations = OrganizationBasicSerializer(many=True, read_only=True)
    set_current_organization = serializers.CharField(write_only=True, required=False)
    set_current_team = serializers.CharField(write_only=True, required=False)
    current_password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "date_joined",
            "uuid",
            "distinct_id",
            "first_name",
            "email",
            "email_opt_in",
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
        extra_kwargs = {
            "date_joined": {"read_only": True},
            "is_staff": {"read_only": True},
            "password": {"write_only": True},
        }

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

    def update(self, instance: models.Model, validated_data: Any) -> Any:

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

        report_user_updated(instance, updated_attrs)

        return instance

    def to_representation(self, instance: Any) -> Any:
        user_identify.identify_task.delay(user_id=instance.id)
        return super().to_representation(instance)


class UserViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = UserSerializer
    permission_classes = [
        permissions.IsAuthenticated,
    ]
    queryset = User.objects.none()
    lookup_field = "uuid"

    def get_object(self) -> Any:
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return self.request.user
        raise serializers.ValidationError(
            "Currently this endpoint only supports retrieving `@me` instance.", code="invalid_parameter",
        )


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
        "dataAttributes": team.data_attributes,
    }

    if settings.JS_URL:
        params["jsURL"] = settings.JS_URL

    if not settings.TEST and not os.environ.get("OPT_OUT_CAPTURE"):
        params["instrument"] = True
        params["userEmail"] = request.user.email
        params["distinctId"] = request.user.distinct_id

    state = urllib.parse.quote(json.dumps(params))

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
