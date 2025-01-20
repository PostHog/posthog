import json

from typing import Any

from django.http import HttpResponse
from django.shortcuts import redirect
from rest_framework import mixins, serializers, viewsets
from posthog.api.utils import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from django.core.cache import cache

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.integration import (
    Integration,
    OauthIntegration,
    SlackIntegration,
    GoogleCloudIntegration,
    GoogleAdsIntegration,
    LinkedInAdsIntegration,
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

        if kind in OauthIntegration.supported_kinds:
            try:
                auth_url = OauthIntegration.authorize_url(kind, next=next)
                return redirect(auth_url)
            except NotImplementedError:
                raise ValidationError("Kind not configured")

        raise ValidationError("Kind not supported")

    @action(methods=["GET"], detail=True, url_path="channels")
    def channels(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        slack = SlackIntegration(instance)

        channels = [
            {
                "id": channel["id"],
                "name": channel["name"],
                "is_private": channel["is_private"],
                "is_member": channel["is_member"],
                "is_ext_shared": channel["is_ext_shared"],
            }
            for channel in slack.list_channels()
        ]

        return Response({"channels": channels})

    @action(methods=["GET"], detail=True, url_path="google_conversion_actions")
    def conversion_actions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        google_ads = GoogleAdsIntegration(instance)
        customer_id = request.query_params.get("customerId")

        conversion_actions = google_ads.list_google_ads_conversion_actions(customer_id)

        if len(conversion_actions) == 0:
            return Response({"conversionActions": []})

        conversion_actions = [
            {
                "id": conversionAction["conversionAction"]["id"],
                "name": conversionAction["conversionAction"]["name"],
                "resourceName": conversionAction["conversionAction"]["resourceName"],
            }
            for conversionAction in google_ads.list_google_ads_conversion_actions(customer_id)[0]["results"]
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
    def conversion_rules(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        linkedin_ads = LinkedInAdsIntegration(instance)
        account_id = request.query_params.get("accountId")

        conversion_actions = [
            {
                "id": conversionAction["conversionAction"]["id"],
                "name": conversionAction["conversionAction"]["name"],
                "resourceName": conversionAction["conversionAction"]["resourceName"],
            }
            for conversionAction in linkedin_ads.list_linkedin_ads_conversion_rules(account_id)[0]["results"]
        ]

        return Response({"conversionActions": conversion_actions})

    @action(methods=["GET"], detail=True, url_path="linkedin_ads_accessible_accounts")
    def accessible_accounts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        linkedin_ads = LinkedInAdsIntegration(instance)

        accessible_accounts = [
            {
                "id": accountId,
            }
            for accountId in linkedin_ads.list_linkedin_ads_accessible_accounts()["resourceNames"]
        ]

        return Response({"accessibleAccounts": accessible_accounts})
