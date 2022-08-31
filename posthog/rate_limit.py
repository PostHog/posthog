from rest_framework.throttling import UserRateThrottle
from sentry_sdk.api import capture_exception

from posthog.internal_metrics import incr


class PassThroughThrottle(UserRateThrottle):
    def allow_request(self, request, view):
        request_would_be_allowed = super().allow_request(request, view)
        if not request_would_be_allowed:
            try:
                scope = getattr(self, "scope", None)
                incr(
                    "rate_limit_exceeded", tags={"team_id": getattr(view, "team_id", None), "scope": scope},
                )
            except Exception as e:
                capture_exception(e)
        return True


class PassThroughBurstRateThrottle(PassThroughThrottle):
    scope = "burst"


class PassThroughSustainedRateThrottle(PassThroughThrottle):
    scope = "sustained"


class DestroyClickhouseModelThrottle(UserRateThrottle):
    rate = "10/hour"

    def allow_request(self, request, view):
        # Only throttle DELETE requests
        if request.method == "DELETE":
            return super().allow_request(request, view)
        return True
