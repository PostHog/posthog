import os
import json
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import (
    ClickUpIntegration,
    DatabricksIntegration,
    DatabricksIntegrationError,
    EmailIntegration,
    GitHubIntegration,
    GitLabIntegration,
    GoogleAdsIntegration,
    GoogleCloudIntegration,
    Integration,
    LinearIntegration,
    LinkedInAdsIntegration,
    OauthIntegration,
    SlackIntegration,
    TwilioIntegration,
)


class NativeEmailIntegrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField()
    provider = serializers.ChoiceField(choices=["ses", "mailjet", "maildev"] if settings.DEBUG else ["ses", "mailjet"])


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

            serializer = NativeEmailIntegrationSerializer(data=config)
            serializer.is_valid(raise_exception=True)

            instance = EmailIntegration.create_native_integration(
                serializer.validated_data,
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

        elif validated_data["kind"] == "gitlab":
            config = validated_data.get("config", {})
            hostname = config.get("hostname")
            project_id = config.get("project_id")
            project_access_token = config.get("project_access_token")

            instance = GitLabIntegration.create_integration(
                hostname, project_id, project_access_token, team_id, request.user
            )
            return instance

        elif validated_data["kind"] == "twilio":
            config = validated_data.get("config", {})
            account_sid = config.get("account_sid")
            auth_token = config.get("auth_token")

            if not (account_sid and auth_token):
                raise ValidationError("Account SID and auth token must be provided")

            twilio = TwilioIntegration(
                Integration(
                    id=account_sid,
                    team_id=team_id,
                    created_by=request.user,
                    kind="twilio",
                    config={
                        "account_sid": account_sid,
                    },
                    sensitive_config={
                        "auth_token": auth_token,
                    },
                ),
            )

            instance = twilio.integration_from_keys()
            return instance

        elif validated_data["kind"] == "databricks":
            config = validated_data.get("config", {})
            server_hostname = config.get("server_hostname")
            client_id = config.get("client_id")
            client_secret = config.get("client_secret")
            if not (server_hostname and client_id and client_secret):
                raise ValidationError("Server hostname, client ID, and client secret must be provided")

            # ensure all fields are strings
            if not all(isinstance(value, str) for value in [server_hostname, client_id, client_secret]):
                raise ValidationError("Server hostname, client ID, and client secret must be strings")

            try:
                instance = DatabricksIntegration.integration_from_config(
                    team_id=team_id,
                    server_hostname=server_hostname,
                    client_id=client_id,
                    client_secret=client_secret,
                    created_by=request.user,
                )
            except DatabricksIntegrationError as e:
                raise ValidationError(str(e))
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
    scope_object = "integration"
    scope_object_read_actions = ["list", "retrieve", "github_repos"]
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer

    def safely_get_queryset(self, queryset):
        if isinstance(self.request.successful_authenticator, PersonalAPIKeyAuthentication) or isinstance(
            self.request.successful_authenticator, OAuthAccessTokenAuthentication
        ):
            return queryset.filter(kind="github")
        return queryset

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
            app_slug = get_instance_setting("GITHUB_APP_SLUG")
            installation_url = f"https://github.com/apps/{app_slug}/installations/new?{query_params}"
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

    @action(methods=["GET"], detail=True, url_path="twilio_phone_numbers")
    def twilio_phone_numbers(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        twilio = TwilioIntegration(instance)
        force_refresh: bool = request.query_params.get("force_refresh", "false").lower() == "true"

        key = f"twilio/{instance.integration_id}/phone_numbers"
        data = cache.get(key)

        if data is not None and not force_refresh:
            return Response(data)

        response = {
            "phone_numbers": [
                {
                    "sid": phone_number["sid"],
                    "phone_number": phone_number["phone_number"],
                    "friendly_name": phone_number["friendly_name"],
                }
                for phone_number in twilio.list_twilio_phone_numbers()
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

        if not conversion_actions or "results" not in conversion_actions[0]:
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

    @action(methods=["GET"], detail=True, url_path="clickup_spaces")
    def clickup_spaces(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        clickup = ClickUpIntegration(instance)
        workspace_id = request.query_params.get("workspaceId")

        spaces = [
            {
                "id": space["id"],
                "name": space["name"],
            }
            for space in clickup.list_clickup_spaces(workspace_id)["spaces"]
        ]

        return Response({"spaces": spaces})

    @action(methods=["GET"], detail=True, url_path="clickup_lists")
    def clickup_lists(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        clickup = ClickUpIntegration(instance)
        space_id = request.query_params.get("spaceId")

        all_lists = []

        raw_folders = clickup.list_clickup_folders(space_id)
        for folder in raw_folders.get("folders", []):
            for list_item in folder.get("lists", []):
                all_lists.append(
                    {
                        "id": list_item["id"],
                        "name": list_item["name"],
                        "folder_id": folder["id"],
                        "folder_name": folder["name"],
                    }
                )

        raw_folderless_lists = clickup.list_clickup_folderless_lists(space_id)
        for list_item in raw_folderless_lists.get("lists", []):
            all_lists.append(
                {
                    "id": list_item["id"],
                    "name": list_item["name"],
                }
            )

        return Response({"lists": all_lists})

    @action(methods=["GET"], detail=True, url_path="clickup_workspaces")
    def clickup_workspaces(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        clickup = ClickUpIntegration(instance)

        workspaces = [
            {
                "id": workspace["id"],
                "name": workspace["name"],
            }
            for workspace in clickup.list_clickup_workspaces()["teams"]
        ]

        return Response({"workspaces": workspaces})

    @action(methods=["GET"], detail=True, url_path="linear_teams")
    def linear_teams(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        linear = LinearIntegration(self.get_object())
        return Response({"teams": linear.list_teams()})

    @action(methods=["GET"], detail=True, url_path="github_repos")
    def github_repos(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        github = GitHubIntegration(self.get_object())
        return Response({"repositories": github.list_repositories()})

    @action(methods=["POST"], detail=True, url_path="email/verify")
    def email_verify(self, request, **kwargs):
        email = EmailIntegration(self.get_object())
        verification_result = email.verify()
        return Response(verification_result)
