from rest_framework.throttling import UserRateThrottle

from posthog.internal_metrics import incr


class PassThroughMixin:
    def allow_request(self, request, view):
        request_would_be_allowed = super().allow_request(request, view)
        if not request_would_be_allowed:
            scope = getattr(self, "scope", None)
            rate = self.get_rate() if scope else None
            history = getattr(self, "history", None)
            count_reqeusts_made = len(history) if history else None
            team_id = request.GET.get("project_id")
            incr(
                "rate_limit_exceeded",
                tags={
                    "class": view.__class__.__name__,
                    "view": getattr(view, "name", None),
                    "user_id": request.user.id,
                    "team_id": team_id,
                    "scope": scope,
                    "rate": rate,
                    "count_reqeusts_made": count_reqeusts_made,
                },
            )
        return True


class PassThroughBurstRateThrottle(PassThroughMixin, UserRateThrottle):
    scope = "burst"


class PassThroughSustainedRateThrottle(PassThroughMixin, UserRateThrottle):
    scope = "sustained"
