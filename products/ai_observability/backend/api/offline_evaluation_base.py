from rest_framework import viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.permissions import AccessControlPermission, PostHogFeatureFlagPermission

from products.ai_observability.backend.api.offline_experiment_errors import validation_errors
from products.ai_observability.backend.offline_evaluation_service import (
    OfflineEvaluationNotFound,
    OfflineEvaluationValidationError,
)


class OfflineEvaluationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "evaluation"
    requires_resource_level_access = True
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions: list[str] = []
    permission_classes = [AccessControlPermission, PostHogFeatureFlagPermission]
    posthog_feature_flag = "ai-observability-offline-evaluations"

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, OfflineEvaluationNotFound):
            exc = NotFound("Offline evaluation resource not found.")
        elif isinstance(exc, OfflineEvaluationValidationError):
            exc = ValidationError(exc.errors)
        response = super().handle_exception(exc)
        if isinstance(exc, ValidationError):
            errors = validation_errors(exc.detail)
            if errors:
                response.data.update(errors[0], errors=errors)
        return response
