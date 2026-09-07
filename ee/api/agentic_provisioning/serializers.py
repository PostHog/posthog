"""Request serializers for the agentic provisioning endpoints.

Error codes, messages, and check order are part of the partner wire contract
(documented at posthog.com/docs/integrate/provisioning), not DRF's default
error shape, so validators raise :class:`ProvisioningError` (rendered by the
view in its envelope) instead of DRF ``ValidationError``.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework import serializers

from posthog.api.oauth.client_assertion import CLIENT_ASSERTION_TYPE_JWT_BEARER

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.credentials import validate_label_prefix
from ee.api.agentic_provisioning.exceptions import ProvisioningError


def first_error_message(errors: Any) -> str:
    """Flatten DRF field errors into a single wire-compatible message."""
    if isinstance(errors, dict):
        for field, messages in errors.items():
            nested = first_error_message(messages)
            return f"{field}: {nested}" if nested else str(field)
    if isinstance(errors, list) and errors:
        return first_error_message(errors[0])
    return str(errors)


class AccountRequestSerializer(serializers.Serializer):
    """POST /provisioning/account_requests body."""

    # Optional fields carry allow_null=True: an explicit null is treated the
    # same as an omitted field (coerced to the declared default in validate)
    # rather than rejected with a 400.
    id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="Partner-side account request id, echoed back for idempotency.",
    )
    email = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text="Email of the account to create or link. Required.",
    )
    name = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default="", help_text="Display name of the end user."
    )
    scopes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        default=list,
        help_text="OAuth scopes requested for the eventual access token. Defaults to the app's grantable set.",
    )
    expires_at = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="ISO-8601 expiry of the account request; expired requests are rejected.",
    )
    configuration = serializers.JSONField(
        required=False,
        allow_null=True,
        default=dict,
        help_text="Partner configuration: region (US/EU), organization_name, wizard block.",
    )
    code_challenge = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="PKCE code challenge (S256, base64url).",
    )
    code_challenge_method = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="S256",
        help_text="PKCE challenge method; only S256 is supported.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Treat explicit null on optional fields as absent, so downstream code
        # sees the declared default rather than None.
        attrs["id"] = attrs.get("id") or ""
        attrs["scopes"] = attrs.get("scopes") or []
        attrs["code_challenge"] = attrs.get("code_challenge") or ""
        attrs["code_challenge_method"] = attrs.get("code_challenge_method") or "S256"

        if not attrs.get("email"):
            capture_provisioning_event("account_request", "error", error_code="missing_email")
            raise ProvisioningError("invalid_request", "email is required")

        expires_at_str = attrs.get("expires_at") or ""
        if expires_at_str:
            # parse_datetime returns None for non-ISO-8601 input but raises
            # ValueError for well-formed yet invalid values (e.g. month 13);
            # both count as unparseable and are ignored, matching the historic
            # "reject only when parseable and in the past" behavior.
            try:
                expires_at = parse_datetime(expires_at_str)
            except ValueError:
                expires_at = None
            if expires_at and expires_at < timezone.now():
                capture_provisioning_event("account_request", "error", error_code="expired")
                raise ProvisioningError("expired", "Account request has expired")

        if not isinstance(attrs.get("configuration"), dict):
            attrs["configuration"] = {}

        return attrs


class GitHubGrantCreateSerializer(serializers.Serializer):
    """POST /provisioning/github/grants body."""

    code = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="GitHub OAuth authorization code to exchange server-side.",
    )
    redirect_uri = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text="redirect_uri used in the GitHub OAuth authorize step, when one was sent.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        code = attrs.get("code")
        if not code or not isinstance(code, str):
            capture_provisioning_event(
                "github_grant", "error", partner=self.context.get("partner"), error_code="missing_code"
            )
            raise ProvisioningError("invalid_request", "code is required")
        attrs["redirect_uri"] = attrs.get("redirect_uri") or None
        return attrs


class ResourceCreateSerializer(serializers.Serializer):
    """POST /provisioning/resources body."""

    project_id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="Partner-side project id; idempotency key for the provisioned project.",
    )
    configuration = serializers.JSONField(
        required=False, allow_null=True, default=dict, help_text="Partner configuration: project_name."
    )
    label_prefix = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional prefix for the label of the provisioned personal API key (max 25 chars).",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            attrs["label_prefix"] = validate_label_prefix(attrs.get("label_prefix"))
        except ProvisioningError:
            capture_provisioning_event(
                "resource_created", "error", partner=self.context.get("partner"), error_code="invalid_label_prefix"
            )
            raise

        attrs["project_id"] = attrs.get("project_id") or ""
        if not isinstance(attrs.get("configuration"), dict):
            attrs["configuration"] = {}

        return attrs


class RotateCredentialsSerializer(serializers.Serializer):
    """POST /provisioning/resources/:id/rotate_credentials body."""

    label_prefix = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional prefix for the label of the re-issued personal API key (max 25 chars).",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            attrs["label_prefix"] = validate_label_prefix(attrs.get("label_prefix"))
        except ProvisioningError as exc:
            capture_provisioning_event("credential_rotation", "error", error_code="invalid_label_prefix")
            exc.resource_id = self.context.get("resource_id", "")
            raise

        return attrs


class GitHubIntegrationSerializer(serializers.Serializer):
    """POST /provisioning/resources/:id/github_integration body."""

    grant_id = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Opaque grant id returned by POST /provisioning/github/grants.",
    )
    installation_id = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="GitHub App installation id chosen by the user in the repo picker.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("grant_id") or not attrs.get("installation_id"):
            raise ProvisioningError(
                "invalid_request",
                "grant_id and installation_id are required",
                resource_id=self.context.get("resource_id", ""),
            )
        return attrs


class WizardRunSerializer(serializers.Serializer):
    """POST /provisioning/resources/:id/wizard_runs body."""

    repository = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Repository to run the setup wizard against, in 'owner/repo' form.",
    )
    branch = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text="Branch to base the wizard run on; defaults to the repository's default branch.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("repository"):
            raise ProvisioningError(
                "invalid_request", "repository is required", resource_id=self.context.get("resource_id", "")
            )
        attrs["branch"] = attrs.get("branch") or None
        return attrs


class DeepLinkSerializer(serializers.Serializer):
    """POST /provisioning/deep_links body."""

    purpose = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="dashboard",
        help_text="Free-form label retained for analytics (e.g. dashboard).",
    )
    path = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Relative in-app path the user lands on after login; must start with a single '/'.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs["purpose"] = attrs.get("purpose") or "dashboard"
        return attrs


class ClientRegistrationSerializer(serializers.Serializer):
    """POST /provisioning/client_registration body."""

    client_id = serializers.CharField(
        help_text=(
            "The client_id to register and diagnose. For a CIMD client this is the https URL of "
            "its own metadata document, which is what gets fetched."
        ),
    )
    client_assertion = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text=(
            "Optional private_key_jwt assertion to verify end to end, so a partner can confirm "
            "its signing setup before relying on it. Verifying consumes the assertion's jti, so "
            "send one minted for this check rather than reusing it afterwards."
        ),
    )
    client_assertion_type = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text=("Must be urn:ietf:params:oauth:client-assertion-type:jwt-bearer when client_assertion is sent."),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs["client_assertion"] = attrs.get("client_assertion") or ""
        attrs["client_assertion_type"] = attrs.get("client_assertion_type") or ""
        if attrs["client_assertion"] and attrs["client_assertion_type"] != CLIENT_ASSERTION_TYPE_JWT_BEARER:
            raise ProvisioningError(
                "invalid_request",
                f"client_assertion_type must be {CLIENT_ASSERTION_TYPE_JWT_BEARER}",
            )
        return attrs
