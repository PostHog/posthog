import os
import re
import json
from typing import Any, cast
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

import requests
import structlog
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.github_callback import state as github_callback_state
from posthog.api.github_callback.team_services import (
    build_team_oauth_authorize_url,
    create_team_github_integration_from_oauth_code,
    link_existing_team_github_integration,
)
from posthog.api.github_callback.types import (
    FlowKind,
    GitHubAuthorizeState,
    github_app_install_url,
    is_valid_github_installation_id,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.auth import SessionAuthentication
from posthog.domain_connect import discover_domain_connect, extract_root_domain_and_host, get_available_providers
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.helpers.fuzzy_search import fuzzy_filter
from posthog.models import OrganizationMembership, User
from posthog.models.integration import (
    ANTHROPIC_DEFAULT_INTEGRATION_ID_PREFIX,
    ANTHROPIC_MANAGED_AGENT_LIST_PAGE_LIMIT,
    ANTHROPIC_WORKSPACE_LABEL_MAX_LENGTH,
    ERROR_TOKEN_REFRESH_FAILED,
    GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS,
    SLACK_INTEGRATION_KINDS,
    AnthropicIntegration,
    AwsS3Integration,
    AzureBlobIntegration,
    AzureBlobIntegrationError,
    ClickUpIntegration,
    DatabricksIntegration,
    DatabricksIntegrationError,
    EmailIntegration,
    FirebaseIntegration,
    GitHubIntegration,
    GitHubIntegrationError,
    GitLabIntegration,
    GoogleAdsIntegration,
    GoogleCloudIntegration,
    GoogleCloudServiceAccountIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
    LinkedInAdsIntegration,
    OauthIntegration,
    PostgreSQLIntegration,
    S3CompatibleIntegration,
    S3CredentialIntegrationError,
    SlackIntegration,
    StripeIntegration,
    TwilioIntegration,
    defer_repository_cache_fields,
)
from posthog.models.user_integration import UserIntegration
from posthog.permissions import (
    AccessControlPermission,
    APIScopePermission,
    TeamMemberAccessPermission,
    TeamMemberLightManagementPermission,
    TeamMemberStrictManagementPermission,
)
from posthog.rate_limit import GitHubRepositoryRefreshThrottle
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.tasks.email import send_integration_access_request
from posthog.utils import is_relative_url

from products.cdp.backend.services.integration_usage import get_enabled_hog_functions_using_integration
from products.workflows.backend.services.integration_usage import get_active_hog_flows_using_integration

logger = structlog.get_logger(__name__)

GITHUB_REPOSITORY_NAME_RE = re.compile(r"[A-Za-z0-9_.\-]+")

# Short TTL for the Search Console sites dropdown — just enough to dedupe repeated UI loads.
GSC_AUTOCOMPLETE_CACHE_TTL_SECONDS = 60


def validate_github_repository_name(repo: str) -> str:
    """Validate repository paths accepted by GitHub integration endpoints."""
    parts = repo.split("/")
    if (
        len(parts) != 2
        or not GITHUB_REPOSITORY_NAME_RE.fullmatch(parts[0])
        or not GITHUB_REPOSITORY_NAME_RE.fullmatch(parts[1])
        or parts[0] in (".", "..")
        or parts[1] in (".", "..")
    ):
        raise ValidationError("repo must be in owner/repo format")
    return repo


def _verify_stripe_install_signature(state: str, user_id: str, account_id: str, install_signature: str) -> bool:
    """Verify Stripe Apps marketplace install signature.

    Stripe signs the redirect with HMAC over the JSON object {state, user_id, account_id}
    in that exact key order using the app's signing secret. Without this check, a forged
    callback URL could link an attacker's Stripe account onto a victim's PostHog team.

    See: https://docs.stripe.com/stripe-apps/install-links-oauth
    """
    if not install_signature or not settings.STRIPE_SIGNING_SECRET:
        return False

    import stripe  # noqa: PLC0415

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

    def validate_email(self, value: str) -> str:
        return value.lower()


class GitHubRepoSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="GitHub repository numeric identifier.")
    name = serializers.CharField(help_text="Repository short name (without the owner prefix).")
    full_name = serializers.CharField(help_text="Fully-qualified repository name as 'owner/repo'.")
    # The fields below come free from GitHub's installation/repositories payload. They are optional so
    # repositories cached before this change (which stored only id/name/full_name) still validate.
    private = serializers.BooleanField(required=False, help_text="Whether the repository is private.")
    default_branch = serializers.CharField(required=False, help_text="The repository's default branch (e.g. 'main').")
    language = serializers.CharField(
        required=False, help_text="Primary programming language GitHub detected for the repository."
    )
    pushed_at = serializers.CharField(
        required=False,
        help_text="ISO 8601 timestamp of the most recent push, useful for sorting by recent activity.",
    )
    archived = serializers.BooleanField(required=False, help_text="Whether the repository is archived.")
    can_push = serializers.BooleanField(
        required=False,
        help_text="Whether the PostHog GitHub App has write access — required to open pull requests.",
    )


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


class JiraProjectSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Jira project ID.")
    key = serializers.CharField(help_text="Jira project key to pass as error tracking config.project_key.")
    name = serializers.CharField(help_text="Jira project display name.")


class JiraProjectsResponseSerializer(serializers.Serializer):
    projects = JiraProjectSerializer(many=True, help_text="Jira projects available to this integration.")


class LinearTeamSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Linear team ID to pass as error tracking config.team_id.")
    name = serializers.CharField(help_text="Linear team display name.")


class LinearTeamsResponseSerializer(serializers.Serializer):
    teams = LinearTeamSerializer(many=True, help_text="Linear teams available to this integration.")


class GitHubTeamSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="GitHub team numeric identifier.")
    slug = serializers.CharField(help_text="GitHub team slug.")
    name = serializers.CharField(help_text="GitHub team display name.")


class GitHubTeamsQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional case-insensitive team name or slug search query.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
        max_value=500,
        help_text="Maximum number of teams to return per request (max 500).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of teams to skip before returning results.",
    )


class GitHubTeamsResponseSerializer(serializers.Serializer):
    teams = GitHubTeamSerializer(
        many=True, help_text="List of GitHub teams available to the installation organization."
    )
    has_more = serializers.BooleanField(help_text="Whether more teams are available beyond this page.")


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


class SlackChannelsQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional case-insensitive channel name or ID search query.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        max_value=200,
        help_text="Maximum number of channels to return per request (max 200).",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Number of channels to skip before returning results.",
    )


class SlackChannelsResponseSerializer(serializers.Serializer):
    channels = SlackChannelSerializer(many=True, help_text="Slack channels visible to the PostHog Slack app.")
    lastRefreshedAt = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="ISO 8601 timestamp of the last full Slack API refresh (only set on full lists, not single-channel lookups).",
    )
    has_more = serializers.BooleanField(
        required=False,
        help_text="Whether more channels match the current search beyond this page.",
    )


class GoogleSearchConsoleSiteSerializer(serializers.Serializer):
    siteUrl = serializers.CharField(
        help_text=(
            "Site URL in canonical Google format — `https://example.com/` for URL-prefix "
            "properties (trailing slash mandatory) or `sc-domain:example.com` for Domain properties."
        )
    )
    permissionLevel = serializers.CharField(
        help_text=(
            "The connected user's permission level for this site. One of `siteOwner`, "
            "`siteFullUser`, `siteRestrictedUser`, `siteUnverifiedUser`."
        )
    )


class GoogleSearchConsoleSitesResponseSerializer(serializers.Serializer):
    sites = GoogleSearchConsoleSiteSerializer(many=True)


class IntegrationAccessRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=Integration.IntegrationKind.choices,
        help_text="The kind of integration the member is requesting be connected (e.g. 'slack', 'github').",
    )
    reason = serializers.CharField(
        max_length=2000,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Explanation from the requester of why this integration is needed. Shown to admins in the notification email.",
    )


class IntegrationAccessRequestResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(
        help_text="Whether the access request was accepted and the project admins were notified."
    )


@extend_schema_serializer(component_name="IntegrationConfig")
class IntegrationSerializer(serializers.ModelSerializer, UserAccessControlSerializerMixin):
    """Standard Integration serializer."""

    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Integration
        fields = ["id", "kind", "config", "created_at", "created_by", "errors", "display_name"]
        read_only_fields = ["id", "created_at", "created_by", "errors", "display_name"]

    def validate_kind(self, value: str) -> str:
        if value == Integration.IntegrationKind.SLACK_POSTHOG_CODE.value:
            raise ValidationError("This integration kind is deprecated and can no longer be created.")
        return value

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
            return create_team_github_integration_from_oauth_code(
                request=request,
                user=request.user,
                team_id=team_id,
                installation_id=config.get("installation_id"),
                state_token=config.get("state"),
                code=config.get("code"),
            )

        elif validated_data["kind"] == "gitlab":
            config = validated_data.get("config", {})
            hostname = config.get("hostname")
            project_id = config.get("project_id")
            project_access_token = config.get("project_access_token")

            instance = GitLabIntegration.create_integration(
                hostname, project_id, project_access_token, team_id, request.user
            )
            return instance

        elif validated_data["kind"] == "anthropic":
            config = validated_data.get("config", {})
            api_key = config.get("api_key")
            workspace_label = config.get("workspace_label")
            force = bool(config.get("force", False))

            if not isinstance(api_key, str) or not api_key.strip():
                raise ValidationError("An Anthropic API key must be provided")
            api_key = api_key.strip()
            # Reject control characters / whitespace inside the key — pasted
            # tokens with trailing newlines silently break every Anthropic call.
            if any(ch.isspace() or ord(ch) < 0x20 for ch in api_key):
                raise ValidationError("Anthropic API key must not contain whitespace or control characters")

            if workspace_label is not None:
                if not isinstance(workspace_label, str):
                    raise ValidationError("Workspace label must be a string")
                workspace_label = workspace_label.strip()
                if not workspace_label:
                    workspace_label = None
                elif len(workspace_label) > ANTHROPIC_WORKSPACE_LABEL_MAX_LENGTH:
                    raise ValidationError(
                        f"Workspace label must be {ANTHROPIC_WORKSPACE_LABEL_MAX_LENGTH} characters or fewer"
                    )
                elif workspace_label.startswith(ANTHROPIC_DEFAULT_INTEGRATION_ID_PREFIX):
                    raise ValidationError(
                        f"Workspace label cannot start with '{ANTHROPIC_DEFAULT_INTEGRATION_ID_PREFIX}'"
                    )

            instance = AnthropicIntegration.integration_from_key(
                api_key=api_key,
                team_id=team_id,
                created_by=request.user,
                workspace_label=workspace_label,
                force=force,
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

        elif validated_data["kind"] == "aws-s3":
            config = validated_data.get("config", {})
            name = config.get("name")
            aws_access_key_id = config.get("aws_access_key_id")
            aws_secret_access_key = config.get("aws_secret_access_key")

            if not (name and aws_access_key_id and aws_secret_access_key):
                raise ValidationError("Name, access key ID, and secret access key must be provided")
            if not all(isinstance(value, str) for value in (name, aws_access_key_id, aws_secret_access_key)):
                raise ValidationError("Name, access key ID, and secret access key must be strings")

            try:
                instance = AwsS3Integration.integration_from_config(
                    team_id=team_id,
                    name=name,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    created_by=request.user,
                )
            except S3CredentialIntegrationError as e:
                raise ValidationError(str(e))
            return instance

        elif validated_data["kind"] == "s3-compatible":
            config = validated_data.get("config", {})
            name = config.get("name")
            endpoint_url = config.get("endpoint_url")
            aws_access_key_id = config.get("aws_access_key_id")
            aws_secret_access_key = config.get("aws_secret_access_key")

            if not (name and endpoint_url and aws_access_key_id and aws_secret_access_key):
                raise ValidationError("Name, endpoint URL, access key ID, and secret access key must be provided")
            if not all(
                isinstance(value, str) for value in (name, endpoint_url, aws_access_key_id, aws_secret_access_key)
            ):
                raise ValidationError("Name, endpoint URL, access key ID, and secret access key must be strings")

            try:
                # SSRF validation of `endpoint_url` happens inside `integration_from_config`.
                instance = S3CompatibleIntegration.integration_from_config(
                    team_id=team_id,
                    name=name,
                    endpoint_url=endpoint_url,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    created_by=request.user,
                )
            except S3CredentialIntegrationError as e:
                raise ValidationError(str(e))
            return instance

        elif validated_data["kind"] == "postgresql":
            config = validated_data.get("config", {})
            host = config.get("host")
            port = config.get("port", 5432)
            user = config.get("user")
            password = config.get("password")
            ssl_mode = config.get("ssl_mode", "require")
            ssl_root_cert = config.get("ssl_root_cert")

            if not (host and port and user and password):
                raise ValidationError("Host, port, user, and password must be provided")

            if not all(isinstance(value, str) for value in (host, user, password)):
                raise ValidationError("Host, user, and password must be strings")

            from products.batch_exports.backend.api.batch_export import resolve_and_validate_host

            try:
                resolve_and_validate_host(host)
            except ValueError:
                raise ValidationError(f"Invalid host: '{host}'")

            try:
                port = int(port)
            except (TypeError, ValueError):
                raise ValidationError("Port must be an integer")

            if port < 0 or port > 65535:
                raise ValidationError("Port must be between 0 and 65535")

            if ssl_mode not in ("require", "verify-ca", "verify-full"):
                raise ValidationError("SSL mode must be one of: require, verify-ca, verify-full")

            if ssl_mode in ("verify-ca", "verify-full"):
                if not ssl_root_cert:
                    raise ValidationError("Root certificate must be provided when verifying server certificates")
                if not isinstance(ssl_root_cert, str):
                    raise ValidationError("Root certificate must be a string")

            instance = PostgreSQLIntegration.integration_from_config(
                team_id=team_id,
                host=host,
                port=port,
                user=user,
                password=password,
                ssl_mode=ssl_mode,
                ssl_root_cert=ssl_root_cert,
                created_by=request.user,
            )
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


class GitHubPrepareCallbackRequestSerializer(serializers.Serializer):
    next = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Relative URL to redirect to after GitHub setup completes (e.g. account-connected for PostHog Code).",
    )
    installation_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="GitHub installation ID being managed; binds the seeded update state so a callback can't swap in a different installation.",
    )


class GitHubLinkExistingRequestSerializer(serializers.Serializer):
    source_team_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Sibling team in the same organization whose GitHub installation should be reused.",
    )
    installation_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="GitHub installation ID to link; resolved within the organization when source_team_id is omitted.",
    )


class GitHubOAuthAuthorizeRequestSerializer(serializers.Serializer):
    installation_id = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="GitHub installation ID to carry through the User OAuth flow.",
    )
    next = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Relative URL to redirect to after the OAuth flow completes.",
    )
    connect_from = serializers.ChoiceField(
        required=False,
        choices=["posthog_code"],
        help_text="Originating surface for the connect flow; only 'posthog_code' is recognized.",
    )


class GitHubOAuthAuthorizeResponseSerializer(serializers.Serializer):
    oauth_url = serializers.CharField(help_text="GitHub User OAuth URL the client should redirect to.")


def github_rate_limited_response(exc: GitHubRateLimitError) -> Response:
    """The 429 + Retry-After response for a GitHub rate limit.

    Shared by every GitHub-backed endpoint (integration and user-integration viewsets, signals)
    so the egress ``GitHubRateLimitError`` maps the same way everywhere instead of surfacing a 500.
    """
    response = Response(
        {"detail": "GitHub API rate limit exceeded. Please retry later.", "code": "rate_limited"},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    if exc.retry_after:
        response["Retry-After"] = str(exc.retry_after)
    return response


@extend_schema(extensions={"x-product": "integrations"})
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
        "github_teams",
        "jira_projects",
        "linear_teams",
        "anthropic_managed_agents",
        "anthropic_managed_agent_environments",
        "anthropic_managed_agent_vaults",
    ]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "refresh_github_repos",
        "github_prepare_callback",
        "github_link_existing",
        "github_oauth_authorize",
        # Side-effecting POST (emails admins) — a read-only token must not be able to trigger it.
        "request_access",
        # Enumerates every Search Console property on the connected Google account — gate behind
        # manage access so read-only members can't discover unrelated domains (info disclosure).
        "google_search_console_sites",
    ]
    permission_classes = [TeamMemberStrictManagementPermission]
    queryset = defer_repository_cache_fields(Integration.objects.all())
    serializer_class = IntegrationSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["kind"]

    def handle_exception(self, exc: Exception) -> Response:
        # GitHub rate limits surface from any GitHub-backed action (teams, repos, branches, refresh);
        # map them to 429 + Retry-After once here instead of per action.
        if isinstance(exc, GitHubRateLimitError):
            return github_rate_limited_response(exc)
        return super().handle_exception(exc)

    def dangerously_get_permissions(self):
        if self.action == "refresh_github_repos":
            return [
                IsAuthenticated(),
                APIScopePermission(),
                AccessControlPermission(),
                TeamMemberAccessPermission(),
                TeamMemberLightManagementPermission(),
            ]
        # Any project member may ask an admin to connect an integration — connecting still requires admin.
        if self.action == "request_access":
            return [
                IsAuthenticated(),
                APIScopePermission(),
                AccessControlPermission(),
                TeamMemberAccessPermission(),
            ]
        raise NotImplementedError()

    def get_throttles(self):
        if self.action == "refresh_github_repos":
            return [GitHubRepositoryRefreshThrottle(), *super().get_throttles()]
        return super().get_throttles()

    def perform_destroy(self, instance) -> None:
        flows_using_integration = get_active_hog_flows_using_integration(
            team_id=instance.team_id, integration_id=instance.id
        )
        functions_using_integration = get_enabled_hog_functions_using_integration(
            team_id=instance.team_id, integration_id=instance.id
        )
        used_by = []
        if flows_using_integration:
            flow_names = ", ".join(sorted(flow.name or str(flow.id) for flow in flows_using_integration))
            used_by.append(f"active workflows: {flow_names}")
        if functions_using_integration:
            function_names = ", ".join(
                sorted(function.name or str(function.id) for function in functions_using_integration)
            )
            used_by.append(f"enabled data pipelines: {function_names}")
        if used_by:
            raise ValidationError(
                f"This integration is used by {' and '.join(used_by)}. "
                "Update them to use a different integration before disconnecting it."
            )

        if instance.kind == "stripe":
            try:
                stripe_integration = StripeIntegration(instance)
                stripe_integration.clear_posthog_secrets()
            except Exception as e:
                capture_exception(e)
        if instance.kind == "github" and instance.integration_id:
            # Team integrations own the installation; personal ones are subordinate. When the
            # last team integration for an installation is removed, tear it down everywhere:
            # uninstall the App on GitHub and delete the now-orphaned personal integrations.
            # Other teams still sharing the same GitHub account keep it installed.
            is_last_team_reference = (
                not Integration.objects.filter(kind="github", integration_id=instance.integration_id)
                .exclude(id=instance.id)
                .exists()
            )
            if is_last_team_reference:
                try:
                    GitHubIntegration.uninstall_app_installation(instance.integration_id)
                except Exception as e:
                    capture_exception(e)
                # Separate try so a DB error deleting personal rows isn't masked by the GitHub call.
                try:
                    UserIntegration.objects.filter(kind="github", integration_id=instance.integration_id).delete()
                except Exception as e:
                    capture_exception(e)

        super().perform_destroy(instance)

    @action(methods=["GET"], detail=False)
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        kind = request.GET.get("kind")
        next = request.GET.get("next", "")
        token = os.urandom(33).hex()

        if kind in OauthIntegration.supported_kinds:
            try:
                auth_url = OauthIntegration.authorize_url(kind, next=next, token=token)
                response = redirect(auth_url)
                # nosemgrep: python.django.security.audit.secure-cookies.django-secure-set-cookie (OAuth state, short-lived, needed for cross-site redirect)
                response.set_cookie("ph_oauth_state", token, max_age=60 * 5)

                return response
            except NotImplementedError:
                raise ValidationError("Kind not configured")
        elif kind == "github":
            if next and not is_relative_url(next):
                raise ValidationError("next must be a relative path starting with /")
            state_param = urlencode({"next": next, "token": token})
            installation_url = github_app_install_url(state_param)
            github_callback_state.store_unified_authorize_state(
                GitHubAuthorizeState(
                    token=token,
                    flow=FlowKind.TEAM_INSTALL,
                    user_id=github_callback_state.authenticated_user_id(request),
                    team_id=self.team_id,
                    next_url=next or None,
                ),
            )
            return redirect(installation_url)

        raise ValidationError("Kind not supported")

    @staticmethod
    def _serialize_slack_channel(channel: dict) -> dict:
        return {
            "id": channel["id"],
            "name": channel["name"],
            "is_private": channel["is_private"],
            "is_member": channel.get("is_member", True),
            "is_ext_shared": channel["is_ext_shared"],
            "is_private_without_access": channel.get("is_private_without_access", False),
        }

    @staticmethod
    def _filter_slack_channels_for_search(channels: list[dict], search: str) -> list[dict]:
        visible = [channel for channel in channels if not channel.get("is_private_without_access")]
        query = search.strip()
        if not query:
            return visible
        # Fuzzy-rank by name, then union in any channel whose id contains the query so pasting an id still resolves.
        ranked = fuzzy_filter(query, visible, key=lambda channel: channel["name"])
        ranked_ids = {channel["id"] for channel in ranked}
        id_matches = [
            channel for channel in visible if query.lower() in channel["id"].lower() and channel["id"] not in ranked_ids
        ]
        return ranked + id_matches

    @extend_schema(
        parameters=[SlackChannelsQuerySerializer],
        responses={200: SlackChannelsResponseSerializer},
    )
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

        # Key on the Integration row PK (unique per PostHog team × Slack workspace), not
        # integration_id (the Slack workspace id, shared across teams). Two teams that
        # install the same workspace must not share cached private-channel lists.
        key = f"slack/{instance.id}/{should_include_private_channels}/channels"

        channel_id = request.query_params.get("channel_id")
        if channel_id:
            data = cache.get(key)
            if data is not None:
                for channel in data["channels"]:
                    if channel["id"] == channel_id:
                        return Response({"channels": [channel]})
            channel = slack.get_channel_by_id(channel_id, should_include_private_channels, authed_user)
            if channel:
                return Response({"channels": [self._serialize_slack_channel(channel)]})
            return Response({"channels": []})

        query_serializer = SlackChannelsQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        search = query_serializer.validated_data["search"]
        limit = query_serializer.validated_data["limit"]
        offset = query_serializer.validated_data["offset"]

        data = cache.get(key)

        if data is None or force_refresh:
            data = {
                "channels": [
                    self._serialize_slack_channel(channel)
                    for channel in slack.list_channels(should_include_private_channels, authed_user)
                ],
                "lastRefreshedAt": timezone.now().isoformat(),
            }
            cache.set(key, data, 60 * 60)  # one hour

        filtered_channels = self._filter_slack_channels_for_search(data["channels"], search)
        page = filtered_channels[offset : offset + limit]
        has_more = offset + limit < len(filtered_channels)

        return Response(
            {
                "channels": page,
                "lastRefreshedAt": data.get("lastRefreshedAt"),
                "has_more": has_more,
            }
        )

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

    @extend_schema(responses={200: GoogleSearchConsoleSitesResponseSerializer})
    @action(methods=["GET"], detail=True, url_path="google_search_console_sites")
    def google_search_console_sites(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List the Search Console properties the connected Google account has access to."""
        # Lazy import — keeps the Google data-imports SDK dependency off the api/ module
        # import path, mirroring how other ad-platform endpoints stay self-contained.
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console import (  # noqa: PLC0415 — keeps the heavy dep off the import path
            google_search_console_session,
            list_sites,
        )

        instance = self.get_object()
        if instance.kind != "google-search-console":
            raise ValidationError(
                "google_search_console_sites endpoint is only supported for Google Search Console integrations"
            )
        _ensure_oauth_token_valid(instance)

        cache_key = f"google_search_console/{instance.id}/sites"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        session = google_search_console_session(instance.id, instance.team_id)
        try:
            sites = list_sites(session)
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in (401, 403):
                # The token refreshed fine but the connected Google account isn't authorized to
                # read Search Console — a customer-side connection issue, not a PostHog bug. Return
                # an actionable 400 rather than letting the HTTPError surface as an unhandled 500.
                raise ValidationError(
                    "Google Search Console rejected the credentials. Please reconnect your account "
                    "and ensure it has read access to the property."
                )
            raise
        response_data = {"sites": sites}
        cache.set(cache_key, response_data, GSC_AUTOCOMPLETE_CACHE_TTL_SECONDS)
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

    @extend_schema(responses={200: LinearTeamsResponseSerializer})
    @action(methods=["GET"], detail=True, url_path="linear_teams")
    def linear_teams(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        if instance.kind != "linear":
            raise ValidationError("linear_teams endpoint is only supported for Linear integrations")
        _ensure_oauth_token_valid(instance)
        linear = LinearIntegration(instance)
        return Response({"teams": linear.list_teams()})

    @extend_schema(operation_id="integrations_anthropic_managed_agents_retrieve")
    @action(methods=["GET"], detail=True, url_path="anthropic_managed_agents")
    def anthropic_managed_agents(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._anthropic_managed_list_response(request, resource="agents")

    @extend_schema(operation_id="integrations_anthropic_managed_agent_envs_retrieve")
    @action(methods=["GET"], detail=True, url_path="anthropic_managed_agent_environments")
    def anthropic_managed_agent_environments(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._anthropic_managed_list_response(request, resource="environments")

    @extend_schema(operation_id="integrations_anthropic_managed_agent_vaults_retrieve")
    @action(methods=["GET"], detail=True, url_path="anthropic_managed_agent_vaults")
    def anthropic_managed_agent_vaults(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._anthropic_managed_list_response(request, resource="vaults")

    def _anthropic_managed_list_response(self, request: Request, *, resource: str) -> Response:
        from anthropic import (  # noqa: PLC0415
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            PermissionDeniedError,
        )

        instance = self._get_anthropic_integration_or_400()

        try:
            limit = int(request.query_params.get("limit", ANTHROPIC_MANAGED_AGENT_LIST_PAGE_LIMIT))
        except (TypeError, ValueError):
            raise ValidationError("`limit` must be an integer")
        after = request.query_params.get("after") or None
        force_refresh = request.query_params.get("force_refresh", "false").lower() == "true"

        # Cache only the default first page; paginated requests bypass the
        # cache because the cursor reflects upstream state we shouldn't pin.
        cache_eligible = not after and limit == ANTHROPIC_MANAGED_AGENT_LIST_PAGE_LIMIT
        cache_key = f"anthropic/{instance.id}/{resource}"
        if cache_eligible and not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)

        try:
            anthropic = AnthropicIntegration(instance)
            data, next_cursor = self._anthropic_resource_list(anthropic, resource=resource, after=after, limit=limit)
        except AuthenticationError:
            self._record_anthropic_auth_failure(instance, "Anthropic API key is no longer valid")
            raise ValidationError("Anthropic API key is no longer valid. Please reconnect the integration.")
        except PermissionDeniedError:
            self._record_anthropic_auth_failure(instance, "Anthropic API key is missing required permissions")
            raise ValidationError(
                "Anthropic API key is missing required permissions. Please reconnect with a key that has access "
                "to the Managed Agents beta."
            )
        except APIConnectionError:
            logger.warning("anthropic_list_connection_error", resource=resource, exc_info=True)
            raise ValidationError("Could not reach Anthropic. Please try again.")
        except APIStatusError as e:
            logger.warning("anthropic_list_status_error", resource=resource, status_code=e.status_code, exc_info=True)
            raise ValidationError(f"Anthropic returned an error (HTTP {e.status_code}). Please try again.")

        body: dict[str, Any] = {"next_cursor": next_cursor, "has_more": bool(next_cursor)}
        if resource == "agents":
            body["agents"] = [
                {
                    "id": agent["id"],
                    "name": agent.get("name", agent["id"]),
                    "version": agent.get("version"),
                }
                for agent in data
                if "id" in agent
            ]
        elif resource == "environments":
            body["environments"] = [
                {"id": env["id"], "name": env.get("name", env["id"])} for env in data if "id" in env
            ]
        else:  # vaults
            body["vaults"] = [
                {"id": vault["id"], "display_name": vault.get("display_name", vault["id"])}
                for vault in data
                if "id" in vault
            ]

        if cache_eligible:
            cache.set(cache_key, body, 60 * 5)  # 5 minutes — UI dropdown freshness window

        return Response(body)

    def _get_anthropic_integration_or_400(self) -> Integration:
        instance = self.get_object()
        if instance.kind != Integration.IntegrationKind.ANTHROPIC.value:
            raise ValidationError(f"Integration {instance.id} is not an Anthropic integration (kind={instance.kind!r})")
        return instance

    @staticmethod
    def _anthropic_resource_list(
        anthropic: AnthropicIntegration, *, resource: str, after: str | None, limit: int
    ) -> tuple[list[dict], str | None]:
        if resource == "agents":
            return anthropic.list_managed_agents(after=after, limit=limit)
        if resource == "environments":
            return anthropic.list_managed_agent_environments(after=after, limit=limit)
        if resource == "vaults":
            return anthropic.list_managed_agent_vaults(after=after, limit=limit)
        raise ValueError(f"unknown anthropic managed-agents resource: {resource!r}")

    @staticmethod
    def _record_anthropic_auth_failure(instance: Integration, message: str) -> None:
        if instance.errors != ERROR_TOKEN_REFRESH_FAILED:
            instance.errors = ERROR_TOKEN_REFRESH_FAILED
            instance.save(update_fields=["errors"])
        logger.warning("anthropic_managed_list_auth_failure", integration_id=instance.id, message=message)

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

        instance = self.get_object()
        if instance.kind != "github":
            raise ValidationError("github_repos endpoint is only supported for GitHub integrations")
        github = GitHubIntegration(instance)
        repositories, has_more = github.list_cached_repositories(search=search, limit=limit, offset=offset)

        return Response({"repositories": repositories, "has_more": has_more})

    @extend_schema(request=GitHubPrepareCallbackRequestSerializer, responses={204: None})
    @action(methods=["POST"], detail=False, url_path="github/prepare_callback")
    def github_prepare_callback(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Seed GitHub setup callback state without redirecting to GitHub.

        Used when the user opens an existing installation's settings on github.com (e.g. PostHog
        Code "Update in GitHub") so the subsequent Setup URL redirect can be validated.
        """
        serializer = GitHubPrepareCallbackRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        next_url = str(serializer.validated_data.get("next") or "")
        if next_url and not is_relative_url(next_url):
            raise ValidationError("next must be a relative path starting with /")
        installation_id = str(serializer.validated_data.get("installation_id") or "") or None
        if installation_id is not None and not is_valid_github_installation_id(installation_id):
            raise ValidationError("Invalid installation_id")
        token = os.urandom(33).hex()
        github_callback_state.store_unified_authorize_state(
            GitHubAuthorizeState(
                token=token,
                flow=FlowKind.TEAM_UPDATE,
                user_id=github_callback_state.authenticated_user_id(request),
                team_id=self.team_id,
                installation_id=installation_id,
                next_url=next_url or None,
            ),
        )
        return Response(status=204)

    @extend_schema(
        request=GitHubLinkExistingRequestSerializer,
        responses={200: IntegrationSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="github/link_existing")
    def github_link_existing(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Reuse a GitHub installation already linked to a sibling team in the same organization."""
        instance = link_existing_team_github_integration(
            user=cast(User, request.user),
            organization=self.organization,
            team_id=self.team_id,
            source_team_id=request.data.get("source_team_id"),
            installation_id_param=request.data.get("installation_id"),
        )
        return Response(self.get_serializer(instance).data)

    @extend_schema(
        request=GitHubOAuthAuthorizeRequestSerializer,
        responses={200: GitHubOAuthAuthorizeResponseSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="github/oauth_authorize")
    def github_oauth_authorize(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Mint a User OAuth URL to bootstrap a fresh `code` when the install flow returns without one."""
        oauth_url = build_team_oauth_authorize_url(
            user_id=cast(User, request.user).id,
            team_id=self.team_id,
            installation_id=str(request.data.get("installation_id") or ""),
            next_url=str(request.data.get("next") or ""),
            connect_from=request.data.get("connect_from")
            if request.data.get("connect_from") == "posthog_code"
            else None,
        )
        return Response({"oauth_url": oauth_url})

    @extend_schema(
        request=IntegrationAccessRequestSerializer,
        responses={200: IntegrationAccessRequestResponseSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="request_access")
    def request_access(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Notify project admins that a member is requesting an integration be connected."""
        # Members only — admins can connect integrations themselves, so there's nobody to ask.
        requesting_level = self.user_permissions.current_team.effective_membership_level
        if requesting_level is None or requesting_level >= OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("Only members can request access; admins can connect integrations directly.")

        serializer = IntegrationAccessRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        send_integration_access_request.delay(
            team_id=self.team_id,
            requesting_user_id=cast(User, request.user).id,
            kind=serializer.validated_data["kind"],
            reason=serializer.validated_data["reason"],
        )
        # Keep the free-text reason out of properties (PII + cardinality); a length signal is enough.
        report_user_action(
            cast(User, request.user),
            "integration access requested",
            {
                "integration_kind": serializer.validated_data["kind"],
                "requester_level": requesting_level,
                "reason_length": len(serializer.validated_data["reason"]),
            },
            team=self.team,
        )
        return Response({"success": True})

    @extend_schema(request=None, responses={200: GitHubReposRefreshResponseSerializer})
    @action(methods=["POST"], detail=True, url_path="github_repos/refresh")
    def refresh_github_repos(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        if instance.kind != "github":
            raise ValidationError("refresh_github_repos endpoint is only supported for GitHub integrations")
        github = GitHubIntegration(instance)
        repositories = github.sync_repository_cache(
            min_refresh_interval_seconds=GITHUB_REPOSITORY_REFRESH_COOLDOWN_SECONDS
        )

        return Response({"repositories": repositories})

    @extend_schema(
        parameters=[GitHubTeamsQuerySerializer],
        responses={200: GitHubTeamsResponseSerializer},
    )
    @action(methods=["GET"], detail=True, url_path="github_teams")
    def github_teams(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query_serializer = GitHubTeamsQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        search = query_serializer.validated_data["search"]
        limit = query_serializer.validated_data["limit"]
        offset = query_serializer.validated_data["offset"]

        github = GitHubIntegration(self.get_object())
        try:
            teams, has_more = github.list_teams(search=search, limit=limit, offset=offset)
        except GitHubIntegrationError as err:
            capture_exception(err)
            raise ValidationError(
                "Unable to fetch GitHub teams. Please check integration settings and try again."
            ) from err

        return Response({"teams": teams, "has_more": has_more})

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

        validate_github_repository_name(repo)

        instance = self.get_object()
        if instance.kind != "github":
            raise ValidationError("github_branches endpoint is only supported for GitHub integrations")
        github = GitHubIntegration(instance)
        branches, default_branch, has_more = github.list_cached_branches(
            repo,
            search=search,
            limit=limit,
            offset=offset,
        )

        return Response({"branches": branches, "default_branch": default_branch, "has_more": has_more})

    @extend_schema(responses={200: JiraProjectsResponseSerializer})
    @action(methods=["GET"], detail=True, url_path="jira_projects")
    def jira_projects(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        if instance.kind != "jira":
            raise ValidationError("jira_projects endpoint is only supported for Jira integrations")
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
