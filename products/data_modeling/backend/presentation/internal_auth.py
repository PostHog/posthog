"""Authentication for the data_modeling_ops internal (service-to-service) API.

Scoped JWTs signed with a dedicated per-audience key (DATA_MODELING_OPS_JWT_SECRET),
short-lived and pinned to a team, so a leaked token is useless outside its team and
expiry window. See .agents/security.md (secrets & service-to-service auth).
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from django.apps import apps
from django.conf import settings

import jwt
import structlog
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import InternalAPIAuthentication, InternalAPIUser

logger = structlog.get_logger(__name__)

DATA_MODELING_OPS_AUDIENCE = "posthog:data_modeling_ops"
JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_EXPIRY = timedelta(minutes=5)


def _verification_keys() -> list[str]:
    return [
        key for key in [settings.DATA_MODELING_OPS_JWT_SECRET, *settings.DATA_MODELING_OPS_JWT_SECRET_FALLBACKS] if key
    ]


def mint_data_modeling_ops_token(
    team_id: int,
    acting_user: str,
    expiry_delta: timedelta = DEFAULT_TOKEN_EXPIRY,
) -> str:
    """Mint a token accepted by DataModelingOpsJWTAuthentication.

    Used by tests and local tooling; the modeling-ops app mints its own tokens with the
    shared signing key. ``acting_user`` identifies the human behind the service call for
    audit logging.
    """
    if not settings.DATA_MODELING_OPS_JWT_SECRET:
        raise ValueError("DATA_MODELING_OPS_JWT_SECRET is not configured")
    return jwt.encode(
        {
            "aud": DATA_MODELING_OPS_AUDIENCE,
            "exp": datetime.now(tz=UTC) + expiry_delta,
            "team_id": team_id,
            "acting_user": acting_user,
        },
        settings.DATA_MODELING_OPS_JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


class DataModelingOpsJWTAuthentication(InternalAPIAuthentication):
    """DRF authentication for data_modeling_ops internal API requests.

    Requires ``Authorization: Bearer <jwt>`` where the token carries the
    data_modeling_ops audience, an expiry, and a ``team_id`` claim matching the
    team in the requested URL. Subclasses InternalAPIAuthentication so the router's
    internal-service permission short-circuit applies, but replaces the shared-secret
    credential with a scoped JWT (see .agents/security.md).
    """

    keyword = "Bearer"

    def _requested_team_id(self, request: Request) -> Optional[str]:
        parser_context = getattr(request, "parser_context", None)
        if isinstance(parser_context, dict):
            kwargs = parser_context.get("kwargs")
            if isinstance(kwargs, dict) and kwargs.get("team_id") is not None:
                return str(kwargs["team_id"])

        django_request = getattr(request, "_request", request)
        resolver_match = getattr(django_request, "resolver_match", None)
        if resolver_match and getattr(resolver_match, "kwargs", None):
            team_id = resolver_match.kwargs.get("team_id")
            if team_id is not None:
                return str(team_id)

        return None

    def _decode(self, token: str) -> dict[str, Any]:
        keys = _verification_keys()
        if not keys:
            logger.error("data_modeling_ops_auth_not_configured")
            raise AuthenticationFailed("Internal API authentication is not configured.")

        last_error: jwt.InvalidTokenError | None = None
        for key in keys:
            try:
                return jwt.decode(
                    token,
                    key,
                    audience=DATA_MODELING_OPS_AUDIENCE,
                    algorithms=[JWT_ALGORITHM],
                    options={"require": ["exp", "aud"]},
                )
            except jwt.InvalidSignatureError as error:
                last_error = error
            except jwt.InvalidTokenError as error:
                raise AuthenticationFailed("Invalid internal API token.") from error

        raise AuthenticationFailed("Invalid internal API token.") from last_error

    def authenticate(self, request: Request) -> tuple[InternalAPIUser, dict[str, Any]]:
        header = request.headers.get("Authorization", "")
        if not header.startswith(f"{self.keyword} "):
            raise AuthenticationFailed("Missing internal API token.")

        claims = self._decode(header[len(self.keyword) + 1 :].strip())

        requested_team_id = self._requested_team_id(request)
        token_team_id = claims.get("team_id")
        if requested_team_id is None or token_team_id is None or str(token_team_id) != requested_team_id:
            raise AuthenticationFailed("Token is not valid for this team.")

        Team = apps.get_model(app_label="posthog", model_name="Team")
        try:
            team = Team.objects.only("id", "organization_id").get(id=requested_team_id)
        except (Team.DoesNotExist, ValueError):
            raise AuthenticationFailed("Invalid internal API team.")

        logger.info(
            "data_modeling_ops_internal_request",
            team_id=team.id,
            acting_user=claims.get("acting_user"),
            path=request.path,
        )
        return (InternalAPIUser(current_organization_id=team.organization_id, current_team_id=team.id), claims)

    def authenticate_header(self, request: Request) -> str:
        return self.keyword
