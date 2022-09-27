from rest_framework.throttling import SimpleRateThrottle
from sentry_sdk.api import capture_exception

from posthog.internal_metrics import incr


class PassThroughTeamRateThrottle(SimpleRateThrottle):
    def allow_request(self, request, view):
        """
        This function is being used as we're figuring out what our throttle limits should be.
        This ensures no rate limits are actually applied, but rather logs that they would have been applied.
        Allowing us to determine appropriate limits without affecting users.
        """
        request_would_be_allowed = super().allow_request(request, view)
        if not request_would_be_allowed:
            try:
                scope = getattr(self, "scope", None)
                incr("rate_limit_exceeded", tags={"team_id": getattr(view, "team_id", None), "scope": scope})
            except Exception as e:
                capture_exception(e)
        return True

    def get_cache_key(self, request, view):
        """
        Attempts to throttle based on the team_id of the request. If it can't do that, it falls back to the user_id.
        And then finally to the IP address.
        """
        if request.user.is_authenticated:
            team_id = getattr(view, "team_id", None)
            if team_id:
                ident = team_id
            else:
                ident = request.user.pk
        else:
            ident = self.get_ident(request)

        return self.cache_format % {"scope": self.scope, "ident": ident}


class PassThroughBurstRateThrottle(PassThroughTeamRateThrottle):
    # Throttle class that's applied on all endpoints (except for capture + decide)
    # Intended to block quick bursts of requests
    scope = "burst"
    rate = "480/minute"


class PassThroughSustainedRateThrottle(PassThroughTeamRateThrottle):
    # Throttle class that's applied on all endpoints (except for capture + decide)
    # Intended to block slower but sustained bursts of requests
    scope = "sustained"
    rate = "4800/hour"


class PassThroughClickHouseBurstRateThrottle(PassThroughTeamRateThrottle):
    # Throttle class that's a bit more aggressive and is used specifically
    # on endpoints that generally hit ClickHouse
    # Intended to block quick bursts of requests
    scope = "clickhouse_burst"
    rate = "240/minute"


class PassThroughClickHouseSustainedRateThrottle(PassThroughTeamRateThrottle):
    # Throttle class that's a bit more aggressive and is used specifically
    # on endpoints that generally hit ClickHouse
    # Intended to block slower but sustained bursts of requests
    scope = "clickhouse_sustained"
    rate = "1200/hour"
