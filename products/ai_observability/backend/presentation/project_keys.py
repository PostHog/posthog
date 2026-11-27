from typing import Literal, cast
from uuid import UUID

from django.db.models import Model, QuerySet

from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.permissions import filter_visible_project_objects, is_service_auth

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.ai_observability.backend.presentation.throttles import (
    OfflineEvaluationReadBurstThrottle,
    OfflineEvaluationReadSustainedThrottle,
    OfflineEvaluationReadTeamBurstThrottle,
    OfflineEvaluationReadTeamSustainedThrottle,
)


def attribution_user(request: Request) -> User | None:
    return None if is_service_auth(request) else cast(User, request.user)


def project_key_id(request: Request) -> str | None:
    authenticator = request.successful_authenticator
    if isinstance(authenticator, ProjectSecretAPIKeyAuthentication):
        return authenticator.project_secret_api_key.id
    return None


def log_project_key_activity(
    request: Request,
    *,
    team: Team,
    scope: Literal["TraceReview", "ScoreDefinition"],
    item_id: UUID,
    activity: Literal["created", "updated", "deleted"],
    changes: list[Change] | None = None,
    previous_project_key_id: str | None = None,
    include_user: bool = False,
) -> None:
    user = attribution_user(request)
    if include_user or user is None or previous_project_key_id is not None:
        log_activity(
            organization_id=team.organization_id,
            team_id=team.id,
            user=user,
            item_id=item_id,
            scope=scope,
            activity=activity,
            detail=Detail(changes=changes),
            was_impersonated=user is not None and is_impersonated(request),
            strict=True,
        )


class AIObservabilityProjectKeyMixin(TeamAndOrgViewSetMixin):
    authentication_classes = [ProjectSecretAPIKeyAuthentication]

    def filter_visible_to_caller[M: Model](self, queryset: QuerySet[M]) -> QuerySet[M]:
        if is_service_auth(self.request):
            return queryset
        return filter_visible_project_objects(
            queryset, team_id=self.team.id, user_id=self.request.user.id, include_all_if_admin=True
        )

    @property
    def reference_access_control(self) -> UserAccessControl | None:
        return None if is_service_auth(self.request) else self.user_access_control

    def get_throttles(self) -> list[BaseThrottle]:
        if is_service_auth(self.request) and self.throttle_classes == APIView.throttle_classes:
            return [
                OfflineEvaluationReadBurstThrottle(),
                OfflineEvaluationReadSustainedThrottle(),
                OfflineEvaluationReadTeamBurstThrottle(),
                OfflineEvaluationReadTeamSustainedThrottle(),
            ]
        return super().get_throttles()
