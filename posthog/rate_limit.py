from rest_framework.throttling import UserRateThrottle
from sentry_sdk.api import capture_exception
from statshog.defaults.django import statsd


class PassThroughThrottle(UserRateThrottle):
    # This class is being used as we're figuring out what our throttle limits should be.
    # This ensures no rate limits are actually applied, but rather logs that they would have been applied.
    # Allowing us to determine appropriate limits without affecting users.
    def allow_request(self, request, view):
        request_would_be_allowed = super().allow_request(request, view)
        if not request_would_be_allowed:
            try:
                scope = getattr(self, "scope", None)
                try:
                    team_id = view.team_id
                except (AttributeError, KeyError):
                    # AttributeError results from view not having a team_id attribute
                    # KeyError results from view.team_id being unspecified (e.g. in an organization-based endpoint)
                    team_id = None
                statsd.incr("rate_limit_exceeded", tags={"team_id": team_id, "scope": scope})
            except Exception as e:
                capture_exception(e)
        return True


class PassThroughBurstRateThrottle(PassThroughThrottle):
    # Throttle class that's applied on all endpoints (except for capture + decide)
    # Intended to block quick bursts of requests
    scope = "burst"
    rate = "480/minute"


class PassThroughSustainedRateThrottle(PassThroughThrottle):
    # Throttle class that's applied on all endpoints (except for capture + decide)
    # Intended to block slower but sustained bursts of requests
    scope = "sustained"
    rate = "4800/hour"


class PassThroughClickHouseBurstRateThrottle(PassThroughThrottle):
    # Throttle class that's a bit more aggressive and is used specifically
    # on endpoints that generally hit ClickHouse
    # Intended to block quick bursts of requests
    scope = "clickhouse_burst"
    rate = "240/minute"


class PassThroughClickHouseSustainedRateThrottle(PassThroughThrottle):
    # Throttle class that's a bit more aggressive and is used specifically
    # on endpoints that generally hit ClickHouse
    # Intended to block slower but sustained bursts of requests
    scope = "clickhouse_sustained"
    rate = "1200/hour"
