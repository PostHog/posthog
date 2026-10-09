"""Access control for the cloud_agents API."""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.exceptions_capture import capture_exception
from posthog.permissions import PostHogFeatureFlagPermission


class CloudAgentsAccessPermission(PostHogFeatureFlagPermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        try:
            return super().has_permission(request, view)
        except ImproperlyConfigured:
            raise
        except Exception as error:
            # A flag service that fails must close the product, not return a server error.
            capture_exception(error)
            self.message = "Cloud agents is not available for this organization."
            return False
