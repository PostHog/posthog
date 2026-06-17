"""
External API endpoints for the Customer analytics product.

These endpoints are used by the CDP worker for workflow actions. Authenticated
via the team secret API token passed as a Bearer token in the Authorization header.
"""

import hashlib
from typing import Any

from django.db.models import Q

import structlog
import posthoganalytics
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.api.tagged_item import set_tags_on_object
from posthog.exceptions_capture import capture_exception
from posthog.models import OrganizationMembership, Tag, Team
from posthog.models.tag import tagify

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG
from products.customer_analytics.backend.models import Account
from products.customer_analytics.backend.models.account import AccountProperties

ASSIGNMENT_ROLE_FIELDS = ("csm", "account_executive", "account_owner")

logger = structlog.get_logger(__name__)


class _ExternalAccountThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token (team secret_api_token)."""

    def get_cache_key(self, request: Request, view: APIView) -> str:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        ident = hashlib.sha256(token.encode()).hexdigest() if token else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ExternalAccountBurstThrottle(_ExternalAccountThrottle):
    scope = "external_account_burst"
    rate = "60/minute"


class ExternalAccountSustainedThrottle(_ExternalAccountThrottle):
    scope = "external_account_sustained"
    rate = "600/hour"


def _customer_analytics_enabled(team: Team) -> bool:
    organization_id = str(team.organization_id)
    return bool(
        posthoganalytics.feature_enabled(
            CUSTOMER_ANALYTICS_CSP_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def _authenticate_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Extract Bearer token from Authorization header and validate against a team."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, Response({"error": "Missing or invalid Authorization header"}, status=status.HTTP_401_UNAUTHORIZED)

    api_key = auth_header[7:].strip()
    if not api_key:
        return None, Response({"error": "Empty API key"}, status=status.HTTP_401_UNAUTHORIZED)

    # Authenticate against secret_api_token (not api_token) because api_token
    # is the public project key embedded in client-side JS and visible to anyone.
    try:
        team = Team.objects.get(Q(secret_api_token=api_key) | Q(secret_api_token_backup=api_key))
    except (Team.DoesNotExist, Team.MultipleObjectsReturned):
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    # Same 401 as an unknown token: a valid secret token for a team without customer
    # analytics enabled must not be usable to read account data.
    if not _customer_analytics_enabled(team):
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    return team, None


def _serialize_account(account: Account) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "external_id": account.external_id,
        "name": account.name,
        "properties": account.properties.model_dump(mode="json"),
        "tags": sorted(account.tagged_items.values_list("tag__name", flat=True)),
    }


def _get_account_by_external_id(team: Team, external_id: str) -> Account | None:
    try:
        return Account.objects.for_team(team.id).get(external_id=external_id)
    except Account.DoesNotExist:
        return None


class ExternalAccountUpdateSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=400)
    # Each role accepts a `posthog_assignee` value `{type, id}`, `null` to clear, or is
    # omitted to leave unchanged. Roles (RBAC) are rejected — accounts assign users only.
    # `validate` normalizes a provided assignment down to the user id; the view resolves
    # the email against an org membership so the stored `{id, email}` is always trusted.
    csm = serializers.JSONField(required=False, allow_null=True)
    account_executive = serializers.JSONField(required=False, allow_null=True)
    account_owner = serializers.JSONField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=200), required=False, max_length=100)
    tags_mode = serializers.ChoiceField(choices=["add", "set", "remove"], required=False, default="add")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        for field in ASSIGNMENT_ROLE_FIELDS:
            if field in attrs and attrs[field] is not None:
                attrs[field] = self._normalize_assignee(field, attrs[field])
        return attrs

    def _normalize_assignee(self, field: str, value: Any) -> int:
        if not isinstance(value, dict):
            raise serializers.ValidationError({field: "Must be an assignee object or null"})
        if value.get("type") != "user":
            raise serializers.ValidationError({field: "Accounts can only be assigned to users, not roles"})
        try:
            return int(value.get("id"))
        except (TypeError, ValueError):
            raise serializers.ValidationError({field: "Assignee id must be a user id"})


def _apply_tags(account: Account, tags: list[str], mode: str) -> None:
    normalized = list({tagify(t) for t in tags})
    if mode == "remove":
        account.tagged_items.filter(tag__name__in=normalized).delete()
    elif mode == "set":
        set_tags_on_object(normalized, account)
    else:
        for tag_name in normalized:
            tag, _ = Tag.objects.get_or_create(name=tag_name, team_id=account.team_id)
            account.tagged_items.get_or_create(tag_id=tag.id)


class ExternalAccountView(APIView):
    """
    GET /api/customer_analytics/external/account?external_id=<external_id> — Fetch account data
    PATCH /api/customer_analytics/external/account — Update an account's role contacts and tags

    Authenticated via Bearer token (team secret_api_token) in Authorization header.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ExternalAccountBurstThrottle, ExternalAccountSustainedThrottle]

    def get(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        external_id = request.query_params.get("external_id", "").strip()
        if not external_id:
            return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        account = _get_account_by_external_id(team, external_id)
        if account is None:
            return Response({"error": "Account not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(_serialize_account(account))

    def patch(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        serializer = ExternalAccountUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        external_id = data["external_id"].strip()
        if not external_id:
            return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        account = _get_account_by_external_id(team, external_id)
        if account is None:
            return Response({"error": "Account not found"}, status=status.HTTP_404_NOT_FOUND)

        error = self._apply_role_assignments(team, account, data)
        if error:
            return error

        if "tags" in data:
            try:
                _apply_tags(account, data["tags"], data.get("tags_mode", "add"))
            except Exception as e:
                capture_exception(e, {"account_id": str(account.id)})
                return Response({"error": "Failed to update tags"}, status=status.HTTP_400_BAD_REQUEST)

        account.refresh_from_db()
        return Response(_serialize_account(account))

    def _apply_role_assignments(self, team: Team, account: Account, data: dict[str, Any]) -> Response | None:
        properties = dict(account._properties or {})
        changed = False

        for field in ASSIGNMENT_ROLE_FIELDS:
            if field not in data:
                continue
            user_id = data[field]
            if user_id is None:
                properties[field] = None
            else:
                membership = (
                    OrganizationMembership.objects.select_related("user")
                    .filter(organization_id=team.organization_id, user_id=user_id)
                    .first()
                )
                if membership is None:
                    return Response(
                        {"error": f"{field}: user is not a member of this organization"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                properties[field] = {"id": membership.user.id, "email": membership.user.email}
            changed = True

        if not changed:
            return None

        try:
            account.properties = AccountProperties.model_validate(properties)
        except Exception as e:
            capture_exception(e, {"account_id": str(account.id)})
            return Response({"error": "Invalid account properties"}, status=status.HTTP_400_BAD_REQUEST)

        account.save(update_fields=["_properties", "updated_at"])
        return None
