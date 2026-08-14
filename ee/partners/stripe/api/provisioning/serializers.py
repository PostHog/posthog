"""Request serializers for the Stripe provisioning endpoints.

Error codes, messages, and check order are part of the APP 0.1d wire contract,
not DRF's default error shape, so validators raise :class:`SpecError`
(rendered by the view in the spec envelope) instead of DRF ``ValidationError``.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework import serializers

from ee.partners.stripe.api.provisioning.analytics import capture_provisioning_event
from ee.partners.stripe.api.provisioning.constants import VALID_SERVICE_IDS
from ee.partners.stripe.api.provisioning.core import validate_label_prefix
from ee.partners.stripe.api.provisioning.exceptions import SpecError


def first_error_message(errors: Any) -> str:
    """Flatten DRF field errors into a single spec-compatible message."""
    if isinstance(errors, dict):
        for field, messages in errors.items():
            nested = first_error_message(messages)
            return f"{field}: {nested}" if nested else str(field)
    if isinstance(errors, list) and errors:
        return first_error_message(errors[0])
    return str(errors)


class AccountRequestSerializer(serializers.Serializer):
    """POST /provisioning/account_requests body (spec §Account Requests)."""

    # Optional fields carry allow_null=True: per the spec's JSON-compatibility
    # rule, an explicit null is treated the same as an omitted field (coerced to
    # the declared default in validate) rather than rejected with a 400.
    id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="Orchestrator-side account request id, echoed back.",
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
        help_text="OAuth scopes requested for the eventual access token.",
    )
    confirmation_secret = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="Opaque orchestrator confirmation secret.",
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
        help_text="Provider-specific configuration: region (US/EU), organization_name, team_id.",
    )
    orchestrator = serializers.JSONField(
        required=False,
        allow_null=True,
        default=dict,
        help_text='Orchestrator identity block; for Stripe: {"type": "stripe", "stripe": {"account": "acct_..."}}.',
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
        # Treat explicit null on optional fields as absent (spec JSON tolerance),
        # so downstream code sees the declared default rather than None.
        attrs["id"] = attrs.get("id") or ""
        attrs["scopes"] = attrs.get("scopes") or []
        attrs["confirmation_secret"] = attrs.get("confirmation_secret") or ""
        attrs["code_challenge"] = attrs.get("code_challenge") or ""
        attrs["code_challenge_method"] = attrs.get("code_challenge_method") or "S256"

        if not attrs.get("email"):
            capture_provisioning_event("account_request", "error", error_code="missing_email")
            raise SpecError("invalid_request", "email is required")

        expires_at_str = attrs.get("expires_at") or ""
        if expires_at_str:
            # This runs before the signature check, so it must never raise
            # anything but SpecError: parse_datetime returns None for
            # non-ISO-8601 input but raises ValueError for well-formed yet
            # invalid values (e.g. month 13).
            try:
                expires_at = parse_datetime(expires_at_str)
            except ValueError:
                expires_at = None
            if expires_at is None:
                capture_provisioning_event("account_request", "error", error_code="invalid_expires_at")
                raise SpecError("invalid_request", "expires_at must be a valid ISO 8601 timestamp")
            if timezone.is_naive(expires_at):
                # The spec's ISO 8601 permits offset-less values; take them as UTC.
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < timezone.now():
                capture_provisioning_event("account_request", "error", error_code="expired")
                raise SpecError("expired", "Account request has expired")

        if not isinstance(attrs.get("configuration"), dict):
            attrs["configuration"] = {}
        if not isinstance(attrs.get("orchestrator"), dict):
            attrs["orchestrator"] = {}

        return attrs


class ResourceCreateSerializer(serializers.Serializer):
    """POST /provisioning/resources body (spec §Resources)."""

    service_id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="Requested service: free, pay_as_you_go, or analytics. Defaults to analytics.",
    )
    project_id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="Orchestrator-side project id; idempotency key for the provisioned project.",
    )
    configuration = serializers.JSONField(
        required=False, allow_null=True, default=dict, help_text="Provider-specific configuration: project_name."
    )
    label_prefix = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional prefix for the label of the provisioned personal API key (max 25 chars).",
    )
    payment_credentials = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text='Stripe Shared Payment Token block: {"type": "stripe_payment_token", "stripe_payment_token": ...}.',
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        application = self.context.get("application")

        service_id = attrs.get("service_id") or ""
        if service_id and service_id not in VALID_SERVICE_IDS:
            capture_provisioning_event("resource_created", "error", partner=application, error_code="unknown_service")
            raise SpecError("unknown_service", f"Unknown service_id: {service_id}")

        try:
            attrs["label_prefix"] = validate_label_prefix(attrs.get("label_prefix"))
        except SpecError:
            capture_provisioning_event(
                "resource_created", "error", partner=application, error_code="invalid_label_prefix"
            )
            raise

        if not isinstance(attrs.get("configuration"), dict):
            attrs["configuration"] = {}

        return attrs


class UpdateServiceSerializer(serializers.Serializer):
    """POST /provisioning/resources/:id/update_service body."""

    service_id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="Target service: free, pay_as_you_go, or analytics. Required.",
    )
    payment_credentials = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text='Stripe Shared Payment Token block: {"type": "stripe_payment_token", "stripe_payment_token": ...}.',
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        resource_id = self.context.get("resource_id", "")

        service_id = attrs.get("service_id") or ""
        if not service_id:
            raise SpecError("missing_service_id", "service_id is required", resource_id=resource_id)
        if service_id not in VALID_SERVICE_IDS:
            raise SpecError("unknown_service", f"Unknown service_id: {service_id}", resource_id=resource_id)

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
        except SpecError as exc:
            capture_provisioning_event("credential_rotation", "error", error_code="invalid_label_prefix")
            exc.resource_id = self.context.get("resource_id", "")
            raise

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
