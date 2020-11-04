import json
import os
import secrets
import urllib.parse
from typing import Any, Dict, List, Optional, Union, cast

import posthoganalytics
import requests
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Model
from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect
from django.shortcuts import redirect
from rest_framework import exceptions, mixins, permissions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.serializers import raise_errors_on_nested_writes
from rest_framework.utils import model_meta

from posthog.models import User
from posthog.plugins import can_configure_plugins_via_api, can_install_plugins_via_api
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
    plugin_access = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "current_organization_id",
            "current_team_id",
            "name",
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
            "plugin_access",
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

    def get_plugin_access(self, user: User) -> Dict[str, bool]:
        return {"install": can_install_plugins_via_api(), "configure": can_configure_plugins_via_api()}

    def update(self, instance: Model, validated_data: Any) -> Any:
        instance = cast(User, instance)
        raise_errors_on_nested_writes('update', self, validated_data)
        info = model_meta.get_field_info(instance)
        m2m_fields = []
        for attr, value in validated_data.items():
            if attr == 'current_organization_id':
                instance.current_organization = instance.organizations.get(id=value)
                instance.current_team = instance.organization.teams.first()
            if attr == 'current_team_id':
                instance.current_team = instance.organization.teams.get(id=value)
            if attr in info.relations and info.relations[attr].to_many:
                m2m_fields.append((attr, value))
            else:
                setattr(instance, attr, value)
        instance.save()
        for attr, value in m2m_fields:
            field = getattr(instance, attr)
            field.set(value)
        return instance

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
        current_password = request.data.get("current_password")
        new_password = request.data.get("new_password")
        new_password_repeat = request.data.get("new_password_repeat")
        
        user = cast(User, self.get_object())
        if user.has_usable_password():
            if not current_password:
                raise exceptions.ValidationError("Missing current password!")
            if not user.check_password(current_password):
                raise exceptions.ValidationError("Incorrect current password!")
        if not new_password:
            raise exceptions.ValidationError("Missing new password!")
        if new_password != new_password_repeat:
            raise exceptions.ValidationError("New password and repeated new password don't match!")
        try:
            validate_password(new_password, user)
        except ValidationError as e:
            raise exceptions.ValidationError(str(e))
        user.set_password(new_password)
        user.save()
        update_session_auth_hash(cast(WSGIRequest, request), user)
        return Response(UserSerializer(user).data)
