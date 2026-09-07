"""
External API endpoints for the Customer analytics product.

The single-account endpoints are used by the CDP worker for workflow actions and
authenticate via the team secret API token passed as a Bearer token in the
Authorization header. The bulk account list instead authenticates via a project
secret API key carrying the ``account:read`` scope, because the team token is
readable by every project member and must not unlock a team-wide account export.

The team token deliberately grants single-account writes (create, tags,
relationships, custom property values) without per-user ``account`` scope checks:
workflow executions have no acting user to authorize, and the token is only
readable by members of the project whose accounts it writes. Security reviewers
periodically flag this as a write-permission bypass — it is the accepted model
for this surface, matching the resource-level scoping note in the product's
CLAUDE.md.

The view holds only HTTP concerns — Bearer auth, throttles, the feature-flag gate,
request validation, and mapping facade results to responses. Data access, the
transactional write, org-membership resolution, tag application, and exception
capture live behind ``facade.api``.
"""

import hashlib
from typing import Any, cast
from uuid import UUID

from django.db.models import Q
from django.http import HttpRequest

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.api.utils import ErrorResponseSerializer
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.models import Team
from posthog.permissions import get_authenticator_scopes, is_authenticated_via_project_secret_api_key
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.customer_analytics.backend.facade import api as facade
from products.customer_analytics.backend.facade.constants import CUSTOMER_ANALYTICS_CSP_FLAG
from products.customer_analytics.backend.presentation.views.account_actions import (
    ACCOUNT_ACTION_AUTH_COUNTER,
    ExternalAccountCreateSerializer,
    ExternalAccountCustomPropertiesSerializer,
    handle_account_create,
    handle_account_get,
    handle_account_set_properties,
    handle_account_update,
)

logger = structlog.get_logger(__name__)

EXTERNAL_ACCOUNT_LIST_MAX_LIMIT = 100
EXTERNAL_ACCOUNT_LIST_REQUIRED_SCOPE = "account:read"


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


class ExternalAccountListBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "external_account_list_burst"
    rate = ExternalAccountBurstThrottle.rate


class ExternalAccountListSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "external_account_list_sustained"
    rate = ExternalAccountSustainedThrottle.rate


class ExternalAccountListTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "external_account_list_psak_team_burst"
    rate = ExternalAccountBurstThrottle.rate


class ExternalAccountListTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "external_account_list_psak_team_sustained"
    rate = ExternalAccountSustainedThrottle.rate


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


class ExternalAccountListAuthentication(ProjectSecretAPIKeyAuthentication):
    def authenticate(self, request: HttpRequest | Request) -> tuple[Any, None] | None:
        result = super().authenticate(request)
        if result is None or not _customer_analytics_enabled(self.project_secret_api_key.team):
            return None
        return result


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


def _authenticate_psak_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Resolve the team from a project secret API key with the ``account:read`` scope."""
    if not is_authenticated_via_project_secret_api_key(request):
        return None, Response({"error": "Missing or invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    authenticator = cast(ProjectSecretAPIKeyAuthentication, request.successful_authenticator)
    psak = authenticator.project_secret_api_key

    key_scopes = set(get_authenticator_scopes(authenticator) or [])
    valid_scopes = {
        EXTERNAL_ACCOUNT_LIST_REQUIRED_SCOPE,
        EXTERNAL_ACCOUNT_LIST_REQUIRED_SCOPE.replace(":read", ":write"),
    }
    if "*" not in key_scopes and key_scopes.isdisjoint(valid_scopes):
        return None, Response(
            {"error": f"API key missing required scope '{EXTERNAL_ACCOUNT_LIST_REQUIRED_SCOPE}'"},
            status=status.HTTP_403_FORBIDDEN,
        )

    return psak.team, None


class ExternalAccountAssignmentSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="PostHog user id of the assigned user.")
    email = serializers.CharField(help_text="Email address of the assigned user.")


class ExternalAccountSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Account UUID.")
    external_id = serializers.CharField(
        allow_null=True, help_text="External account key — the group key the account is linked to."
    )
    name = serializers.CharField(help_text="Human-readable account name.")
    churned_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the account churned, or null if it has not churned.",
    )
    ignored_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When Track Rules ignored the account, or null if it is tracked.",
    )
    properties = serializers.DictField(
        child=serializers.JSONField(help_text="Property value: a string or null."),
        help_text="Typed account properties: external-system ids. Role assignments live under `relationships`.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(), help_text="Tag names on the account, sorted alphabetically."
    )
    relationships = serializers.DictField(
        child=ExternalAccountAssignmentSerializer(many=True),
        help_text=(
            "Active relationship assignments keyed by definition name (e.g. 'CSM'). "
            "Definitions with no active assignment are omitted."
        ),
    )
    custom_properties = serializers.DictField(
        child=serializers.JSONField(help_text="The property's active scalar value, or null when unset."),
        help_text="Every team custom property definition keyed by name, with the account's active value or null.",
    )


class ExternalAccountErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="What went wrong with the request.")


class ExternalAccountView(APIView):
    """
    GET /api/customer_analytics/external/account?external_id=<external_id> — Fetch account data
    POST /api/customer_analytics/external/account — Create an account (no-op if it already exists)
    PATCH /api/customer_analytics/external/account — Update an account's relationships, tags, and churn state

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
        ACCOUNT_ACTION_AUTH_COUNTER.labels(auth_method="secret_api_token", http_method="get").inc()

        external_id = request.query_params.get("external_id", "").strip()
        if not external_id:
            return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        return handle_account_get(team, external_id)

    @extend_schema(
        request=ExternalAccountCreateSerializer,
        responses={
            201: OpenApiResponse(response=ExternalAccountSerializer, description="Account created."),
            200: OpenApiResponse(
                response=ExternalAccountSerializer, description="Account already existed — creation skipped."
            ),
            400: OpenApiResponse(response=ExternalAccountErrorSerializer, description="Invalid request body."),
            401: OpenApiResponse(
                response=ExternalAccountErrorSerializer, description="Missing or invalid Bearer token."
            ),
        },
    )
    def post(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None
        ACCOUNT_ACTION_AUTH_COUNTER.labels(auth_method="secret_api_token", http_method="post").inc()
        return handle_account_create(request, team)

    def patch(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None
        ACCOUNT_ACTION_AUTH_COUNTER.labels(auth_method="secret_api_token", http_method="patch").inc()
        return handle_account_update(request, team)


class ExternalAccountListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False,
        default=EXTERNAL_ACCOUNT_LIST_MAX_LIMIT,
        help_text=(
            "Maximum number of accounts to return. Values below 1 are clamped to 1; values above 100 are clamped to 100."
        ),
    )
    cursor = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Account UUID from `next_cursor` to continue listing from. Omit for the first page.",
    )
    assigned_only = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "When true, return only accounts with at least one active relationship assignment "
            "to a current member of the project's organization."
        ),
    )
    include_ignored = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Include ignored accounts. Ignored accounts are hidden by default.",
    )

    def validate_limit(self, value: int) -> int:
        return max(1, min(value, EXTERNAL_ACCOUNT_LIST_MAX_LIMIT))

    def validate_cursor(self, value: str) -> str | None:
        if not value:
            return None
        try:
            UUID(value)
        except ValueError:
            raise serializers.ValidationError("Must be a valid account id.")
        return value


class ExternalAccountListAssignmentSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="PostHog user id of the assigned user.")
    email = serializers.CharField(help_text="Current email address of the assigned user.")
    name = serializers.CharField(
        allow_null=True,
        help_text="Current display name of the assigned user, or null when the user has no name set.",
    )


class ExternalAccountListItemSerializer(serializers.Serializer):
    external_id = serializers.CharField(help_text="External account key used by downstream systems.")
    name = serializers.CharField(help_text="Human-readable account name.")
    churned_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the account churned, or null if it has not churned.",
    )
    ignored_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When Track Rules ignored the account, or null if it is tracked.",
    )
    relationships = serializers.DictField(
        child=ExternalAccountListAssignmentSerializer(many=True),
        help_text=(
            "Active relationship assignments to current organization members, keyed by relationship definition name "
            "(e.g. 'CSM', 'Account executive'). Definitions with no active assignment are omitted."
        ),
    )


class ExternalAccountListPageSerializer(serializers.Serializer):
    results = ExternalAccountListItemSerializer(
        many=True,
        help_text="Accounts in this page, ordered by account id.",
    )
    next_cursor = serializers.CharField(
        allow_null=True,
        help_text="Account UUID to pass as `cursor` for the next page, or null when the list is exhausted.",
    )


class ExternalAccountListValidationErrorSerializer(serializers.Serializer):
    error = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        help_text="Validation errors keyed by query parameter.",
    )


class ExternalAccountListView(APIView):
    """
    GET /api/customer_analytics/external/accounts — List accounts with their relationship assignments

    Cursor-paginated by account id. ``assigned_only=true`` restricts the listing
    to accounts with at least one active relationship assignment, which is what
    the billing service's ownership sync consumes.

    Authenticated via a project secret API key (Bearer ``phs_...``) carrying the
    ``account:read`` scope, not the team secret_api_token the sibling views
    accept. The team token is readable by any project member, so it must not
    grant this team-wide export; a PSAK is a service credential minted with an
    explicit scope.
    """

    authentication_classes = [ExternalAccountListAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [
        ExternalAccountListBurstThrottle,
        ExternalAccountListSustainedThrottle,
        ExternalAccountListTeamBurstThrottle,
        ExternalAccountListTeamSustainedThrottle,
    ]
    scope_object = "account"

    @extend_schema(
        parameters=[ExternalAccountListQuerySerializer],
        responses={
            200: OpenApiResponse(response=ExternalAccountListPageSerializer, description="Page of external accounts."),
            400: OpenApiResponse(
                response=ExternalAccountListValidationErrorSerializer,
                description="Invalid query parameters.",
            ),
            401: OpenApiResponse(response=ErrorResponseSerializer, description="Authentication failed."),
            403: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="API key does not carry the account:read scope.",
            ),
        },
        summary="List external customer analytics accounts",
        description=(
            "List tracked accounts with external IDs, lifecycle timestamps, and active relationship assignments. "
            "Set `include_ignored=true` to include ignored accounts. Requires a project secret API key with the "
            "`account:read` scope."
        ),
    )
    def get(self, request: Request) -> Response:
        team, error = _authenticate_psak_team(request)
        if error:
            return error

        assert team is not None

        query_serializer = ExternalAccountListQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response({"error": query_serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        query_data = query_serializer.validated_data

        page = facade.list_external_accounts(
            team.id,
            organization_id=team.organization_id,
            cursor=query_data.get("cursor"),
            limit=query_data["limit"],
            assigned_only=query_data["assigned_only"],
            include_ignored=query_data["include_ignored"],
        )
        return Response(ExternalAccountListPageSerializer(page).data)


class ExternalAccountCustomPropertiesView(APIView):
    """
    PATCH /api/customer_analytics/external/account/custom_property_values — Set an account's custom
    property values, addressing each property by its definition id (UUID).

    Authenticated via Bearer token (team secret_api_token) in the Authorization header.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ExternalAccountBurstThrottle, ExternalAccountSustainedThrottle]

    @extend_schema(request=ExternalAccountCustomPropertiesSerializer, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None
        ACCOUNT_ACTION_AUTH_COUNTER.labels(auth_method="secret_api_token", http_method="patch").inc()
        return handle_account_set_properties(request, team)
