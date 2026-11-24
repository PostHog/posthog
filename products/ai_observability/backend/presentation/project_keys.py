from typing import cast

from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.models import User
from posthog.permissions import is_service_auth

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.ai_observability.backend.presentation.throttles import (
    OfflineEvaluationReadBurstThrottle,
    OfflineEvaluationReadSustainedThrottle,
    OfflineEvaluationReadTeamBurstThrottle,
    OfflineEvaluationReadTeamSustainedThrottle,
)


def attribution_user(request: Request) -> User | None:
    return None if is_service_auth(request) else cast(User, request.user)


class AIObservabilityProjectKeyMixin(TeamAndOrgViewSetMixin):
    authentication_classes = [ProjectSecretAPIKeyAuthentication]

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
