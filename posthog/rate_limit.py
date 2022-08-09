from django.urls.base import resolve
from rest_framework.throttling import UserRateThrottle
from sentry_sdk.api import capture_exception

from posthog.internal_metrics import incr


class PassThroughMixin(UserRateThrottle):
    def allow_request(self, request, view):
        request_would_be_allowed = super().allow_request(request, view)
        if not request_would_be_allowed:
            try:
                route = resolve(request.path)
                route_id = f"{route.route} ({route.func.__name__})"
                scope = getattr(self, "scope", None)
                rate = self.get_rate() if scope else None
                user_id = request.user.pk if request.user.is_authenticated else None
                incr(
                    "rate_limit_exceeded",
                    tags={
                        "route_id": route_id,
                        "action": getattr(view, "action", None),
                        "method": request.method,
                        "user_id": user_id,
                        "team_id": getattr(view, "team_id", None),
                        "organization_id": getattr(view, "organization_id", None),
                        "scope": scope,
                        "rate": rate,
                    },
                )
            except Exception as e:
                capture_exception(e)
        return True


class PassThroughBurstRateThrottle(PassThroughMixin, UserRateThrottle):
    scope = "burst"


class PassThroughSustainedRateThrottle(PassThroughMixin, UserRateThrottle):
    scope = "sustained"
