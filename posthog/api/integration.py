import os
import re
import json
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

import stripe
import requests
import structlog
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.domain_connect import discover_domain_connect, extract_root_domain_and_host, get_available_providers
from posthog.exceptions_capture import capture_exception
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import (
    ERROR_TOKEN_REFRESH_FAILED,
    GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS,
    SLACK_INTEGRATION_KINDS,
    AzureBlobIntegration,
    AzureBlobIntegrationError,
    ClickUpIntegration,
    DatabricksIntegration,
    DatabricksIntegrationError,
    EmailIntegration,
    FirebaseIntegration,
    GitHubInstallationAccess,
    GitHubIntegration,
    GitLabIntegration,
    GoogleAdsIntegration,
    GoogleCloudIntegration,
    GoogleCloudServiceAccountIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
    LinkedInAdsIntegration,
    OauthIntegration,
    SlackIntegration,
    StripeIntegration,
    TwilioIntegration,
    defer_repository_cache_fields,
)
from posthog.models.user_integration import user_github_integration_from_installation
from posthog.permissions import (
    AccessControlPermission,
    APIScopePermission,
    TeamMemberAccessPermission,
    TeamMemberLightManagementPermission,
    TeamMemberStrictManagementPermission,
)
from posthog.rate_limit import GitHubRepositoryRefreshThrottle
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

logger = structlog.get_logger(__name__)


def _verify_stripe_install_signature(state: str, user_id: str, account_id: str, install_signature: str) -> bool:
    """Verify Stripe Apps marketplace install signature.

    Stripe signs the redirect with HMAC over the JSON object {state, user_id, account_id}
    in that exact key order using the app's signing secret. Without this check, a forged
    callback URL could link an attacker's Stripe account onto a victim's PostHog team.

    See: https://docs.stripe.com/stripe-apps/install-links-oauth
    """
    if not install_signature or not settings.STRIPE_SIGNING_SECRET:
        return False
    payload = json.dumps(
        {"state": state, "user_id": user_id, "account_id": account_id},
        separators=(",", ":"),
    )
    try:
        # 300s tolerance matches the agentic-provisioning HMAC check at ee/api/agentic_provisioning/signature.py.
        stripe.WebhookSignature.verify_header(payload, install_signature, settings.STRIPE_SIGNING_SECRET, tolerance=300)
        return True
    except stripe.SignatureVerificationError:
        return False


def _installation_token_expires_at(integration: Integration) -> str:
    """Compute an ISO 8601 timestamp for when the integration's installation token expires."""
    refreshed_at = integration.config.get("refreshed_at", 0)
    expires_in = integration.config.get("expires_in", 3600)
    return datetime.fromtimestamp(refreshed_at + expires_in, tz=UTC).isoformat()


def _ensure_oauth_token_valid(instance: Integration) -> None:
    """Check that an OAuth integration's token is usable, attempting refresh if needed.

    Raises ValidationError with a clear message instead of letting stale tokens
    cause unhandled 500s from external API calls.
    """
    if instance.kind not in OauthIntegration.supported_kinds:
        return

    if instance.errors == ERROR_TOKEN_REFRESH_FAILED:
        raise ValidationError(
            "This integration's authentication token could not be refreshed. "
            "Please reconnect or disconnect this integration and connect a different account."
        )

    oauth = OauthIntegration(instance)
    if oauth.access_token_expired():
        oauth.refresh_access_token()
        if instance.errors == ERROR_TOKEN_REFRESH_FAILED:
            raise ValidationError(
                "This integration's authentication token could not be refreshed. "
                "Please reconnect or disconnect this integration and connect a different account."
            )


class NativeEmailIntegrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField()
    provider = serializers.ChoiceField(choices=["ses", "maildev"] if settings.DEBUG else ["ses"])
    mail_from_subdomain = serializers.CharField(required=False, allow_blank=True)


class GitHubRepoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    full_name = serializers.CharField()


class GitHubReposQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional case-insensitive repository name search query.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=500,
        help_text="Maximum number of repositories to return per request (max 500).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of repositories to skip before returning results.",
    )


class GitHubReposResponseSerializer(serializers.Serializer):
    repositories = GitHubRepoSerializer(many=True)
    has_more = serializers.BooleanField(help_text="Whether more repositories are available beyond this page.")


class GitHubReposRefreshResponseSerializer(serializers.Serializer):
    repositories = GitHubRepoSerializer(many=True, help_text="The refreshed repository cache.")


class GitHubBranchesQuerySerializer(serializers.Serializer):
    repo = serializers.CharField(help_text="Repository in owner/repo format")
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional case-insensitive branch name search query.",
    )
    limit = serializers.IntegerField(
        required=False, default=100, min_value=1, max_value=1000, help_text="Maximum number of branches to return"
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Number of branches to skip")


class GitHubBranchesResponseSerializer(serializers.Serializer):
    branches = serializers.ListField(child=serializers.CharField(), help_text="List of branch names")
    default_branch = serializers.CharField(
        help_text="The default branch of the repository", required=False, allow_null=True
    )
    has_more = serializers.BooleanField(help_text="Whether more branches exist beyond the returned page")


class SlackChannelSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Slack channel ID (e.g. C0123ABC) — pass to cdp-functions inputs.channel.")
    name = serializers.CharField(help_text="Slack channel name without the leading '#'.")
    is_private = serializers.BooleanField(help_text="True if the channel is private.")
    is_member = serializers.BooleanField(
        help_text="True if the PostHog Slack app is a member of the channel and can post to it."
    )
    is_ext_shared = serializers.BooleanField(help_text="True if the channel is shared with another Slack workspace.")
    is_private_without_access = serializers.BooleanField(
        help_text="True if the channel is private and the PostHog Slack app cannot access it."
    )


class SlackChannelsResponseSerializer(serializers.Serializer):
    channels = SlackChannelSerializer(many=True, help_text="Slack channels visible to the PostHog Slack app.")
    lastRefreshedAt = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="ISO 8601 timestamp of the last full Slack API refresh (only set on full lists, not single-channel lookups).",
    )


@extend_schema_serializer(component_name="IntegrationConfig")
class IntegrationSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
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

        elif validated_data["kind"] == "firebase":
            key_file = request.FILES.get("key")
            if not key_file:
                raise ValidationError("Firebase service account key file not provided")
            key_info = json.loads(key_file.read().decode("utf-8"))
            instance = FirebaseIntegration.integration_from_key(key_info, team_id, request.user)
            return instance

        elif validated_data["kind"] == "email":
            config = validated_data.get("config", {})

            serializer = NativeEmailIntegrationSerializer(data=config)
            serializer.is_valid(raise_exception=True)

            get_organization = self.context.get("get_organization")
            if get_organization is None:
                raise ValidationError("Organization context is missing")
            organization_id = str(get_organization().id)

            instance = EmailIntegration.create_native_integration(
                serializer.validated_data,
                team_id=team_id,
                organization_id=organization_id,
                created_by=request.user,
            )
            return instance

        elif validated_data["kind"] == "github":
            config = validated_data.get("config", {})
            installation_id = config.get("installation_id")
            state = config.get("state")
            code = config.get("code")

            if not installation_id:
                raise ValidationError("An installation_id must be provided")

            if not state:
                raise ValidationError("A state token must be provided")

            if not code:
                raise ValidationError("An OAuth code must be provided")

            cache_key = f"github_state:{request.user.id}"
            expected_state = cache.get(cache_key)
            if not expected_state or expected_state != state:
                raise ValidationError("Invalid or expired state token")
            cache.delete(cache_key)

            # Exchange the OAuth code for the user's access token and identity.
            # This requires GITHUB_APP_CLIENT_SECRET to be configured.
            authorization = GitHubIntegration.github_user_from_code(code)
            if authorization is None:
                raise ValidationError(
                    "Failed to exchange the OAuth code — ensure GITHUB_APP_CLIENT_SECRET is configured"
                )

            # Verify the connecting user actually has access to this installation.
            # Without this, an attacker could supply another tenant's installation_id
            # with their own OAuth code and obtain an installation token scoped to
            # the other tenant's repos.
            if not re.fullmatch(r"\d{1,20}", str(installation_id)):
                raise ValidationError("Invalid installation_id")
            try:
                has_access = GitHubIntegration.verify_user_installation_access(
                    installation_id, authorization.access_token
                )
            except requests.RequestException:
                logger.warning(
                    "github_integration_create: installation ownership check failed",
                    installation_id=installation_id,
                    user_id=request.user.id,
                    exc_info=True,
                )
                raise ValidationError("Failed to verify installation access")
            if not has_access:
                logger.warning(
                    "github_integration_create: user does not have access to installation",
                    installation_id=installation_id,
                    user_id=request.user.id,
                )
                raise ValidationError("You do not have access to this GitHub installation")

            instance = GitHubIntegration.integration_from_installation_id(installation_id, team_id, request.user)

            # Store the connecting user's GitHub login on the team integration
            # (shown on the integration card) and auto-create a UserIntegration
            # so the user immediately has personal GitHub credentials for
            # PR authorship and identity attribution
            instance.config["connecting_user_github_login"] = authorization.gh_login
            instance.save(update_fields=["config"])
            # Auto-create a UserIntegration so the user immediately has personal
            # GitHub credentials. create_only=True uses get_or_create atomically —
            # an existing personal integration (e.g. set up via Linked Accounts) is
            # left untouched even under concurrent requests.
            user_github_integration_from_installation(
                request.user,
                GitHubInstallationAccess(
                    installation_id=installation_id,
                    installation_info=instance.config,
                    access_token=instance.sensitive_config.get("access_token", ""),
                    token_expires_at=_installation_token_expires_at(instance),
                    repository_selection=instance.config.get("repository_selection", "selected"),
                ),
                authorization,
                create_only=True,
            )

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

        elif validated_data["kind"] == "google-cloud-service-account":
            config = validated_data.get("config", {})
            service_account_email = config.get("service_account_email")
            project_id = config.get("project_id")
            if not (service_account_email and project_id):
                raise ValidationError("Service account email and project ID must be provided")

            if not all(isinstance(value, str) for value in (service_account_email, project_id)):
                raise ValidationError("Service account email and project ID must be strings")

            get_organization = self.context.get("get_organization")
            if get_organization is None:
                raise ValidationError("Organization context is missing")
            organization_id = str(get_organization().id)

            instance = GoogleCloudServiceAccountIntegration.integration_from_service_account(
                team_id=team_id,
                organization_id=organization_id,
                service_account_email=service_account_email,
                project_id=project_id,
                private_key=config.get("private_key", None),
                private_key_id=config.get("private_key_id", None),
                token_uri=config.get("token_uri", None),
                created_by=request.user,
            )
            return instance

        elif validated_data["kind"] == "azure-blob":
            config = validated_data.get("config", {})
            connection_string = config.get("connection_string")
            if not connection_string:
                raise ValidationError("Connection string must be provided")

            if not isinstance(connection_string, str):
                raise ValidationError("Connection string must be a string")

            try:
                instance = AzureBlobIntegration.integration_from_config(
                    team_id=team_id,
                    connection_string=connection_string,
                    created_by=request.user,
                )
            except AzureBlobIntegrationError as e:
                raise ValidationError(str(e))
            return instance

        elif validated_data["kind"] in OauthIntegration.supported_kinds:
            # Stripe marketplace installs redirect to /integrations/stripe/callback without
            # a PostHog-minted CSRF state token — Stripe drives the OAuth flow itself.
            # Stripe's Connect-OAuth flow (used by stripe_api_access_type: oauth) does not
            # include `install_signature` in the redirect; that param is only emitted for
            # Stripe Apps install-link OAuth. If a signature is present we verify it; if
            # absent we fall through to the conflict guard for defense-in-depth.
            if validated_data["kind"] == "stripe":
                config = validated_data["config"]
                stripe_user_id = config.get("stripe_user_id")
                state = config.get("state")
                if stripe_user_id and not state:
                    install_signature = config.get("install_signature")
                    if install_signature:
                        user_id = config.get("user_id") or ""
                        account_id = config.get("account_id") or ""
                        if not _verify_stripe_install_signature(
                            state="",
                            user_id=user_id,
                            account_id=account_id,
                            install_signature=install_signature,
                        ):
                            capture_exception(
                                Exception("Stripe marketplace callback rejected: invalid install_signature"),
                                {"team_id": team_id, "stripe_user_id": stripe_user_id},
                            )
                            raise ValidationError(
                                "Stripe install signature could not be verified.",
                                code="stripe_install_signature_invalid",
                            )

                    conflicting = (
                        Integration.objects.filter(team_id=team_id, kind="stripe")
                        .exclude(integration_id=stripe_user_id)
                        .exists()
                    )
                    if conflicting:
                        capture_exception(
                            Exception("Stripe marketplace callback rejected: conflicting integration"),
                            {"team_id": team_id, "stripe_user_id": stripe_user_id},
                        )
                        raise ValidationError(
                            "A different Stripe account is already connected to this team. Disconnect it first.",
                            code="stripe_integration_conflict",
                        )

            try:
                instance = OauthIntegration.integration_from_oauth_response(
                    validated_data["kind"], team_id, request.user, validated_data["config"]
                )
            except NotImplementedError:
                raise ValidationError("Kind not configured")

            if validated_data["kind"] == "stripe":
                try:
                    stripe_integration = StripeIntegration(instance)
                    stripe_integration.write_posthog_secrets(team_id, request.user)
                except Exception as e:
                    capture_exception(e)

            return instance

        raise ValidationError("Kind not supported")


@extend_schema(tags=["integrations"])
class IntegrationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "integration"
    scope_object_read_actions = [
        "list",
        "retrieve",
        "channels",
        "github_repos",
        "github_branches",
    ]
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "refresh_github_repos"]
    permission_classes = [TeamMemberStrictManagementPermission]
    queryset = defer_repository_cache_fields(Integration.objects.all())
    serializer_class = IntegrationSerializer

    def dangerously_get_permissions(self):
        if self.action == "refresh_github_repos":
            return [
                IsAuthenticated(),
                APIScopePermission(),
                AccessControlPermission(),
                TeamMemberAccessPermission(),
                TeamMemberLightManagementPermission(),
            ]
        raise NotImplementedError()

    def get_throttles(self):
        if self.action == "refresh_github_repos":
            return [GitHubRepositoryRefreshThrottle(), *super().get_throttles()]
        return super().get_throttles()

    def perform_destroy(self, instance) -> None:
        if instance.kind == "stripe":
            try:
                stripe_integration = StripeIntegration(instance)
                stripe_integration.clear_posthog_secrets()
            except Exception as e:
                capture_exception(e)

        super().perform_destroy(instance)

    def safely_get_queryset(self, queryset):
        if isinstance(self.request.successful_authenticator, PersonalAPIKeyAuthentication) or isinstance(
            self.request.successful_authenticator, OAuthAccessTokenAuthentication
        ):
            # GitHub and Slack integrations are exposed via API-key / OAuth. The serializer
            # only returns id, kind, config, errors, and display metadata — access tokens stay
            # in sensitive_config and are never serialized. The channels action's kind guard
            # (see `channels` below) is the actual gate against running Slack-only code on a
            # non-Slack integration.
            return defer_repository_cache_fields(queryset.filter(kind__in=["github", *SLACK_INTEGRATION_KINDS]))
        return queryset

    @action(methods=["GET"], detail=False)
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        kind = request.GET.get("kind")
        next = request.GET.get("next", "")
        is_sandbox = request.GET.get("is_sandbox", "").lower() in ("true", "1", "yes")
        token = os.urandom(33).hex()

        if kind in OauthIntegration.supported_kinds:
            try:
                auth_url = OauthIntegration.authorize_url(kind, next=next, token=token, is_sandbox=is_sandbox)
                response = redirect(auth_url)
                # nosemgrep: python.django.security.audit.secure-cookies.django-secure-set-cookie (OAuth state, short-lived, needed for cross-site redirect)
                response.set_cookie("ph_oauth_state", token, max_age=60 * 5)

                return response
            except NotImplementedError:
                raise ValidationError("Kind not configured")
        elif kind == "github":
            query_params = urlencode({"state": urlencode({"next": next, "token": token})})
            app_slug = get_instance_setting("GITHUB_APP_SLUG")
            installation_url = f"https://github.com/apps/{app_slug}/installations/new?{query_params}"
            response = redirect(installation_url)
            # nosemgrep: python.django.security.audit.secure-cookies.django-secure-set-cookie (OAuth state, short-lived, needed for cross-site redirect)
            response.set_cookie("ph_github_state", token, max_age=60 * 5)
            # Store server-side so the backend can enforce that the same user who
            # initiated the flow is the one completing it (not just cookie-validated).
            cache.set(f"github_state:{request.user.id}", token, timeout=60 * 5)

            return response

        raise ValidationError("Kind not supported")

    @extend_schema(responses={200: SlackChannelsResponseSerializer})
    @action(methods=["GET"], detail=True, url_path="channels")
    def channels(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        if instance.kind not in SLACK_INTEGRATION_KINDS:
            raise ValidationError("channels endpoint is only supported for Slack integrations")
        slack = SlackIntegration(instance)
        should_include_private_channels: bool = instance.created_by_id == request.user.id
        # force_refresh is only honored for cookie-session callers — MCP / API-key / OAuth
        # callers always read through the 1h cache so an agent loop can't bypass it.
        is_session_auth = isinstance(request.successful_authenticator, SessionAuthentication)
        force_refresh: bool = is_session_auth and request.query_params.get("force_refresh", "false").lower() == "true"
        authed_user = cast(str | None, instance.config.get("authed_user", {}).get("id")) if instance.config else None
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

        # Key on the Integration row PK (unique per PostHog team × Slack workspace), not
        # integration_id (the Slack workspace id, shared across teams). Two teams that
        # install the same workspace must not share cached private-channel lists.
        key = f"slack/{instance.id}/{should_include_private_channels}/channels"
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
        _ensure_oauth_token_valid(instance)
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
        _ensure_oauth_token_valid(instance)
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
        _ensure_oauth_token_valid(instance)
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
        _ensure_oauth_token_valid(instance)
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
        _ensure_oauth_token_valid(instance)
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
        _ensure_oauth_token_valid(instance)
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
        _ensure_oauth_token_valid(instance)
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
        instance = self.get_object()
        _ensure_oauth_token_valid(instance)
        linear = LinearIntegration(instance)
        return Response({"teams": linear.list_teams()})

    @extend_schema(
        parameters=[GitHubReposQuerySerializer],
        responses={200: GitHubReposResponseSerializer},
    )
    @action(methods=["GET"], detail=True, url_path="github_repos")
    def github_repos(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query_serializer = GitHubReposQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        search = query_serializer.validated_data["search"]
        limit = query_serializer.validated_data["limit"]
        offset = query_serializer.validated_data["offset"]

        github = GitHubIntegration(self.get_object())
        repositories, has_more = github.list_cached_repositories(search=search, limit=limit, offset=offset)

        return Response({"repositories": repositories, "has_more": has_more})

    @extend_schema(request=None, responses={200: GitHubReposRefreshResponseSerializer})
    @action(methods=["POST"], detail=True, url_path="github_repos/refresh")
    def refresh_github_repos(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        github = GitHubIntegration(self.get_object())
        repositories = github.sync_repository_cache(
            min_refresh_interval_seconds=GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS
        )

        return Response({"repositories": repositories})

    @extend_schema(
        parameters=[GitHubBranchesQuerySerializer],
        responses={200: GitHubBranchesResponseSerializer},
    )
    @action(methods=["GET"], detail=True, url_path="github_branches")
    def github_branches(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        params = GitHubBranchesQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        repo: str = params.validated_data["repo"]
        search: str = params.validated_data["search"]
        limit: int = params.validated_data["limit"]
        offset: int = params.validated_data["offset"]

        parts = repo.split("/")
        if (
            len(parts) != 2
            or not re.fullmatch(r"[A-Za-z0-9_.\-]+", parts[0])
            or not re.fullmatch(r"[A-Za-z0-9_.\-]+", parts[1])
            or parts[0] in (".", "..")
            or parts[1] in (".", "..")
        ):
            raise ValidationError("repo must be in owner/repo format")

        github = GitHubIntegration(self.get_object())
        branches, default_branch, has_more = github.list_cached_branches(
            repo,
            search=search,
            limit=limit,
            offset=offset,
        )

        return Response({"branches": branches, "default_branch": default_branch, "has_more": has_more})

    @action(methods=["GET"], detail=True, url_path="jira_projects")
    def jira_projects(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        _ensure_oauth_token_valid(instance)
        jira = JiraIntegration(instance)
        return Response({"projects": jira.list_projects()})

    @action(methods=["POST"], detail=True, url_path="email/verify")
    def email_verify(self, request, **kwargs):
        email = EmailIntegration(self.get_object())
        verification_result = email.verify()
        return Response(verification_result)

    @extend_schema(responses={200: IntegrationSerializer})
    @action(methods=["PATCH"], detail=True, url_path="email")
    def email_update(self, request, **kwargs) -> Response:
        instance = self.get_object()
        config = request.data.get("config", {})

        serializer = NativeEmailIntegrationSerializer(data=config)
        serializer.is_valid(raise_exception=True)

        email = EmailIntegration(instance)
        email.update_native_integration(serializer.validated_data, instance.team_id)

        return Response(IntegrationSerializer(email.integration).data)

    @action(methods=["GET"], detail=False, url_path="domain-connect/check")
    def domain_connect_check(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        domain = request.query_params.get("domain", "")
        if not domain:
            raise ValidationError("domain query parameter is required")

        # Extract root domain so subdomains (e.g. ph.example.com) resolve correctly
        root_domain, _ = extract_root_domain_and_host(domain)
        result = discover_domain_connect(root_domain)
        return Response(
            {
                "supported": result is not None,
                "provider_name": result["provider_name"] if result else None,
                "available_providers": get_available_providers() if result is None else [],
            }
        )

    @action(methods=["POST"], detail=False, url_path="domain-connect/apply-url")
    def domain_connect_apply_url(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Unified endpoint for generating Domain Connect apply URLs.

        Accepts a context ("email" or "proxy") and the relevant resource ID.
        The backend resolves the domain, template variables, and service ID
        based on context, then builds the signed apply URL.
        """
        from posthog.domain_connect import (
            DOMAIN_CONNECT_PROVIDERS,
            DomainConnectSigningKeyMissing,
            generate_apply_url,
            resolve_email_context,
            resolve_proxy_context,
        )

        context = request.data.get("context")
        redirect_uri = request.data.get("redirect_uri")
        provider_endpoint = request.data.get("provider_endpoint")

        if provider_endpoint and provider_endpoint not in DOMAIN_CONNECT_PROVIDERS:
            raise ValidationError("Unsupported provider endpoint")

        host: str | None = None

        if context == "email":
            integration_id = request.data.get("integration_id")
            if not integration_id:
                raise ValidationError("integration_id is required for email context")
            try:
                domain, service_id, variables = resolve_email_context(integration_id, self.team_id)
            except ValueError as e:
                capture_exception(e, {"integration_id": integration_id, "team_id": self.team_id, "context": context})
                raise ValidationError(
                    "Validation error resolving email context. Please try again later or contact support."
                )

        elif context == "proxy":
            proxy_record_id = request.data.get("proxy_record_id")
            if not proxy_record_id:
                raise ValidationError("proxy_record_id is required for proxy context")
            organization = self.organization
            try:
                domain, service_id, host, variables = resolve_proxy_context(proxy_record_id, str(organization.id))
            except ValueError as e:
                capture_exception(
                    e, {"proxy_record_id": proxy_record_id, "organization_id": organization.id, "context": context}
                )
                raise ValidationError(
                    "Validation error resolving proxy context. Please try again later or contact support."
                )
        else:
            raise ValidationError("context must be 'email' or 'proxy'")

        try:
            url = generate_apply_url(
                domain=domain,
                service_id=service_id,
                variables=variables,
                host=host,
                provider_endpoint=provider_endpoint,
                redirect_uri=redirect_uri,
            )
        except DomainConnectSigningKeyMissing as e:
            capture_exception(e, {"context": context, "domain": domain, "provider_endpoint": provider_endpoint})
            raise ValidationError(
                "Automatic DNS configuration is temporarily unavailable for this provider. "
                "Please configure your DNS records manually."
            )
        except ValueError as e:
            capture_exception(
                e,
                {
                    "context": context,
                    "domain": domain,
                    "service_id": service_id,
                    "host": host,
                    "provider_endpoint": provider_endpoint,
                    "redirect_uri": redirect_uri,
                },
            )
            raise ValidationError("Error generating apply URL. Please try again later or contact support.")

        return Response({"url": url})
