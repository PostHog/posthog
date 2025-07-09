import json

import os
from typing import Any

from urllib.parse import urlencode
from django.http import HttpResponse
from django.shortcuts import redirect
from rest_framework import mixins, serializers, viewsets
from posthog.api.utils import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from django.core.cache import cache
from django.utils import timezone

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import (
    Integration,
    OauthIntegration,
    SlackIntegration,
    LinearIntegration,
    GoogleCloudIntegration,
    GoogleAdsIntegration,
    LinkedInAdsIntegration,
    EmailIntegration,
    GitHubIntegration,
)


class IntegrationSerializer(serializers.ModelSerializer):
    """Standard Integration serializer."""

    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Integration
        fields = ["id", "kind", "config", "created_at", "created_by", "errors", "display_name"]
        read_only_fields = ["id", "created_at", "created_by", "errors", "display_name"]

    def create(self, validated_data: Any) -> Any:
        request = self.context["request"]
        team_id = self.context["team_id"]

        if validated_data["kind"] in GoogleCloudIntegration.supported_kinds:
            key_file = request.FILES.get("key")
            if not key_file:
                raise ValidationError("Key file not provided")
            key_info = json.loads(key_file.read().decode("utf-8"))
            instance = GoogleCloudIntegration.integration_from_key(
                validated_data["kind"], key_info, team_id, request.user
            )
            return instance

        elif validated_data["kind"] == "email":
            config = validated_data.get("config", {})

            if config.get("api_key") is not None:
                if not (config.get("api_key") and config.get("secret_key")):
                    raise ValidationError("Both api_key and secret_key are required for Mail integration")
                instance = EmailIntegration.integration_from_keys(
                    config["api_key"],
                    config["secret_key"],
                    team_id,
                    request.user,
                )
                return instance

            if not (config.get("domain")):
                raise ValidationError("Domain is required for email integration")
            instance = EmailIntegration.integration_from_domain(
                config["domain"],
                team_id,
                request.user,
            )
            return instance

        elif validated_data["kind"] == "github":
            config = validated_data.get("config", {})
            installation_id = config.get("installation_id")

            if not installation_id:
                raise ValidationError("An installation_id must be provided")

            instance = GitHubIntegration.integration_from_installation_id(installation_id, team_id, request.user)
            return instance

        elif validated_data["kind"] in OauthIntegration.supported_kinds:
            try:
                instance = OauthIntegration.integration_from_oauth_response(
                    validated_data["kind"], team_id, request.user, validated_data["config"]
                )
            except NotImplementedError:
                raise ValidationError("Kind not configured")
            return instance

        raise ValidationError("Kind not supported")


class IntegrationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer

    @action(methods=["GET"], detail=False)
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        kind = request.GET.get("kind")
        next = request.GET.get("next", "")
        token = os.urandom(33).hex()

        if kind in OauthIntegration.supported_kinds:
            try:
                auth_url = OauthIntegration.authorize_url(kind, next=next, token=token)
                response = redirect(auth_url)
                response.set_cookie("ph_oauth_state", token, max_age=60 * 5)

                return response
            except NotImplementedError:
                raise ValidationError("Kind not configured")
        elif kind == "github":
            query_params = urlencode({"state": token})
            installation_url = f"https://github.com/apps/{'posthog-error-tracking'}/installations/new?{query_params}"
            response = redirect(installation_url)
            response.set_cookie("ph_github_state", token, max_age=60 * 5)

            return response

        raise ValidationError("Kind not supported")

    @action(methods=["GET"], detail=True, url_path="channels")
    def channels(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        slack = SlackIntegration(instance)
        should_include_private_channels: bool = instance.created_by_id == request.user.id
        force_refresh: bool = request.query_params.get("force_refresh", "false").lower() == "true"
        authed_user: str = instance.config.get("authed_user", {}).get("id") if instance.config else None
        if not authed_user:
            raise ValidationError("SlackIntegration: Missing authed_user_id in integration config")

        channel_id = request.query_params.get("channel_id")
        if channel_id:
            channel = slack.get_channel_by_id(channel_id, should_include_private_channels, authed_user)
            if channel:
                return Response(
                    {
                        "channels": [
                            {
                                "id": channel["id"],
                                "name": channel["name"],
                                "is_private": channel["is_private"],
                                "is_member": channel.get("is_member", True),
                                "is_ext_shared": channel["is_ext_shared"],
                                "is_private_without_access": channel["is_private_without_access"],
                            }
                        ]
                    }
                )
            else:
                return Response({"channels": []})

        key = f"slack/{instance.integration_id}/{should_include_private_channels}/channels"
        data = cache.get(key)

        if data is not None and not force_refresh:
            return Response(data)

        response = {
            "channels": [
                {
                    "id": channel["id"],
                    "name": channel["name"],
                    "is_private": channel["is_private"],
                    "is_member": channel.get("is_member", True),
                    "is_ext_shared": channel["is_ext_shared"],
                    "is_private_without_access": channel.get("is_private_without_access", False),
                }
                for channel in slack.list_channels(should_include_private_channels, authed_user)
            ],
            "lastRefreshedAt": timezone.now().isoformat(),
        }

        cache.set(key, response, 60 * 60)  # one hour
        return Response(response)

    @action(methods=["GET"], detail=True, url_path="google_conversion_actions")
    def conversion_actions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        google_ads = GoogleAdsIntegration(instance)
        customer_id = request.query_params.get("customerId")
        parent_id = request.query_params.get("parentId")

        conversion_actions = google_ads.list_google_ads_conversion_actions(customer_id, parent_id)

        if len(conversion_actions) == 0:
            return Response({"conversionActions": []})

        conversion_actions = [
            {
                "id": conversionAction["conversionAction"]["id"],
                "name": conversionAction["conversionAction"]["name"],
                "resourceName": conversionAction["conversionAction"]["resourceName"],
            }
            for conversionAction in google_ads.list_google_ads_conversion_actions(customer_id, parent_id)[0]["results"]
        ]

        return Response({"conversionActions": conversion_actions})

    @action(methods=["GET"], detail=True, url_path="google_accessible_accounts")
    def accessible_accounts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        google_ads = GoogleAdsIntegration(instance)

        key = f"google_ads/{google_ads.integration.integration_id}/accessible_accounts"
        data = cache.get(key)

        if data is not None:
            return Response(data)

        response_data = {"accessibleAccounts": google_ads.list_google_ads_accessible_accounts()}
        cache.set(key, response_data, 60)
        return Response(response_data)

    @action(methods=["GET"], detail=True, url_path="linkedin_ads_conversion_rules")
    def linkedin_ad_conversion_rules(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        linkedin_ads = LinkedInAdsIntegration(instance)
        account_id = request.query_params.get("accountId")

        response = linkedin_ads.list_linkedin_ads_conversion_rules(account_id)
        conversion_rules = [
            {
                "id": conversionRule["id"],
                "name": conversionRule["name"],
            }
            for conversionRule in response.get("elements", [])
        ]

        return Response({"conversionRules": conversion_rules})

    @action(methods=["GET"], detail=True, url_path="linkedin_ads_accounts")
    def linkedin_ad_accounts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        linkedin_ads = LinkedInAdsIntegration(instance)

        accounts = [
            {
                "id": account["id"],
                "name": account["name"],
                "reference": account["reference"],
            }
            for account in linkedin_ads.list_linkedin_ads_accounts()["elements"]
        ]

        return Response({"adAccounts": accounts})

    @action(methods=["GET"], detail=True, url_path="linear_teams")
    def linear_teams(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        linear = LinearIntegration(self.get_object())
        return Response({"teams": linear.list_teams()})

    @action(methods=["POST"], detail=True, url_path="email/verify")
    def email_verify(self, request, **kwargs):
        email = EmailIntegration(self.get_object())
        verification_result = email.verify()
        return Response(verification_result)
