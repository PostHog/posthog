"""Helpers that all cloud_agents viewsets share."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from rest_framework import viewsets
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.models.user import User

from ..facade.access import FEATURE_FLAG_KEY
from ..facade.contracts import CallerIdentity
from ..facade.enums import CallerKind
from .errors import CloudAgentsErrorHandlingMixin
from .permissions import CloudAgentsAccessPermission


def caller_from_request(request: Request) -> CallerIdentity:
    user = cast(User, request.user)
    # A session is the PostHog app. A personal API key or an OAuth token is an API client.
    in_app = isinstance(request.successful_authenticator, SessionAuthentication)
    return CallerIdentity(
        user_id=user.id,
        distinct_id=user.distinct_id,
        kind=CallerKind.APP if in_app else CallerKind.API,
        billable=True,
    )


def parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


class CloudAgentsViewSet(CloudAgentsErrorHandlingMixin, TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Base for every cloud_agents viewset: the scope object, the feature flag, and the error mapping."""

    scope_object = "cloud_agent"
    permission_classes = [CloudAgentsAccessPermission]
    posthog_feature_flag = FEATURE_FLAG_KEY
