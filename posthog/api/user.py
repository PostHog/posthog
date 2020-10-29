import json
import os
import secrets
import urllib.parse
from typing import Any, Dict, List, Optional, TypedDict, Union, cast

import posthoganalytics
import requests
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Model
from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect
from django.shortcuts import redirect
from rest_framework import exceptions, mixins, permissions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from posthog.models import User
from posthog.version import VERSION


class OnlyMePermission(permissions.BasePermission):
    """Disallow access to other users."""

    message = "You are not allowed to view other users."

    def has_object_permission(self, request: request.Request, view, object: Model) -> bool:
        return request.user == object


class UserSerializer(serializers.ModelSerializer):
    has_password = serializers.SerializerMethodField(read_only=True)
    opt_out_capture = serializers.SerializerMethodField(read_only=True)
    posthog_version = serializers.SerializerMethodField(read_only=True)
    is_multi_tenancy = serializers.SerializerMethodField(read_only=True)
    ee_available = serializers.SerializerMethodField(read_only=True)
    team = serializers.SerializerMethodField(read_only=True)
    organization = serializers.SerializerMethodField(read_only=True)
    organizations = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "current_organization_id",
            "current_team_id",
            "first_name",
            "email",
            "distinct_id",
            "email_opt_in",
            "anonymize_data",
            "toolbar_mode",
            "has_password",
            "opt_out_capture",
            "posthog_version",
            "is_multi_tenancy",
            "ee_available",
            "team",
            "organization",
            "organizations",
        ]
        read_only_fields = ["id", "email", "distinct_id"]

    def get_has_password(self, user: User) -> bool:
        return user.has_usable_password()

    def get_opt_out_capture(self, user: User) -> bool:
        return bool(os.getenv("OPT_OUT_CAPTURE"))

    def get_posthog_version(self, user: User) -> str:
        return VERSION

    def get_is_multi_tenancy(self, user: User) -> bool:
        return getattr(settings, "MULTI_TENANCY", False)

    def get_ee_available(self, user: User) -> bool:
        return settings.EE_AVAILABLE

    def get_team(self, user: User) -> Optional[Dict[str, Any]]:
        from .team import TeamSerializer

        team = user.team
        return TeamSerializer(user.team).data

    def get_organization(self, user: User) -> Dict[str, Any]:
        from .organization import OrganizationSerializer

        return OrganizationSerializer(user.organization).data

    def get_organizations(self, user: User) -> List[dict]:
        return [row for row in user.organizations.order_by("-created_at").values("name", "id")]  # type: ignore


class UserViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    permission_classes = [permissions.IsAuthenticated, OnlyMePermission]
    lookup_field = "id"

    def get_object(self) -> User:
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return self.request.user
        queryset = (
            self.filter_queryset(self.get_queryset())
            .select_related("current_organization")
            .select_related("current_team")
        )
        filter_kwargs = {self.lookup_field: lookup_value}
        try:
            user = cast(User, get_object_or_404(queryset, **filter_kwargs))
        except ValueError as error:
            raise exceptions.ValidationError(str(error))
        self.check_object_permissions(self.request, user)
        return user

    def perform_update(self, serializer: UserSerializer) -> None:  # type: ignore
        user = cast(User, serializer.instance)
        posthoganalytics.identify(
            user.distinct_id,
            {
                "email_opt_in": user.email_opt_in,
                "anonymize_data": user.anonymize_data,
                "email": user.email if not user.anonymize_data else None,
                "is_signed_up": True,
                "toolbar_mode": user.toolbar_mode,
                "billing_plan": user.organization.billing_plan,
                "is_team_unique_user": (user.team.users.count() == 1),
                "team_setup_complete": (user.team.completed_snippet_onboarding and user.team.ingested_event),
            },
        )
        serializer.save()

    @action(methods=["GET"], detail=True)
    def redirect_to_site(
        self, request: request.Request, id: str
    ) -> Union[response.Response, HttpResponseRedirect, HttpResponsePermanentRedirect]:
        user = self.get_object()
        team = user.team
        app_url = request.GET.get("appUrl") or (team.app_urls and team.app_urls[0])
        use_new_toolbar = user.toolbar_mode != "disabled"

        if not app_url:
            raise exceptions.NotFound()

        user.temporary_token = secrets.token_urlsafe(32)
        user.save()
        params = {
            "action": "ph_authorize",
            "token": team.api_token,
            "temporaryToken": request.user.temporary_token,
            "actionId": request.GET.get("actionId"),
            "userIntent": request.GET.get("userIntent"),
            "toolbarVersion": "toolbar",
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

    @action(methods=["PATCH"], detail=True)
    def change_password(self, request: request.Request, id: str) -> response.Response:
        old_password = request.data.get("oldPassword")
        new_password = request.data.get("newPassword")
        user = cast(User, self.get_object())
        if user.has_usable_password():
            if not old_password:
                raise exceptions.ValidationError("Missing old_password.")
            if not user.check_password(old_password):
                raise exceptions.ValidationError("Incorrect old password.")
        if not new_password:
            raise exceptions.ValidationError("Missing new_password.")
        try:
            validate_password(new_password, user)
        except ValidationError as e:
            raise exceptions.ValidationError("\n".join(e.args[0]))
        user.set_password(new_password)
        user.save()
        update_session_auth_hash(cast(WSGIRequest, request), user)
        return Response()

    @action(methods=["POST"], detail=True)
    def test_slack_webhook(self, request: request.Request, id: str) -> response.Response:
        webhook = request.data.get("webhook")
        if not webhook:
            raise exceptions.ValidationError("Missing webhook URL.")
        message = {"text": "Greetings from PostHog!"}
        try:
            test_response = requests.post(webhook, verify=False, json=message)
            if test_response.ok:
                return Response()
            else:
                raise exceptions.ValidationError(f"Webhook test error: {test_response.text}")
        except:
            raise exceptions.ValidationError("Invalid webhook URL.")

    @action(methods=["POST"], detail=True)
    def switch_organization(self, request: request.Request, id: str) -> response.Response:
        user = self.get_object()
        try:
            user.current_organization = user.organizations.get(id=request.data["organization_id"])
            user.current_team = user.organization.teams.first()
            user.save()
        except KeyError:
            raise exceptions.ValidationError("Missing organization ID.")
        except ObjectDoesNotExist:
            raise exceptions.NotFound()
        else:
            from .organization import OrganizationSerializer

            return Response(OrganizationSerializer(user.current_organization).data)

    @action(methods=["POST"], detail=True)
    def switch_team(self, request: request.Request, id: str) -> response.Response:
        user = self.get_object()
        try:
            user.current_team = user.organization.teams.get(id=int(request.data["team_id"]))
        except ValueError:
            raise exceptions.ValidationError("Team ID must be an integer.")
        except KeyError:
            raise exceptions.ValidationError("Missing team ID.")
        except ObjectDoesNotExist:
            raise exceptions.NotFound()
        else:
            from .team import TeamSerializer

            return Response(TeamSerializer(user.current_team).data)
