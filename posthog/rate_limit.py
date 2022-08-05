from rest_framework.throttling import ScopedRateThrottle

from posthog.internal_metrics import incr


class PassThroughScopedRateLimit(ScopedRateThrottle):
    def allow_request(self, request, view):
        request_would_be_allowed = super().allow_request(request, view)
        if not request_would_be_allowed:
            scope = getattr(view, self.scope_attr, None)
            rate = self.get_rate() if scope else None
            history = getattr(self, "history", None)
            reqeusts_made = len(history) if history else None
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
                    "reqeusts_made": reqeusts_made,
                },
            )
        return True
