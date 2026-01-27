import re
import time
import hashlib
from contextlib import suppress
from functools import lru_cache

from django.conf import settings
from django.urls import resolve

from prometheus_client import Counter
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle
from statshog.defaults.django import statsd

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.metrics import LABEL_PATH, LABEL_ROUTE, LABEL_TEAM_ID
from posthog.models.instance_setting import get_instance_setting
from posthog.models.personal_api_key import hash_key_value
from posthog.models.team.team import Team
from posthog.settings.utils import get_list
from posthog.utils import patchable

RATE_LIMIT_EXCEEDED_COUNTER = Counter(
    "rate_limit_exceeded_total",
    "Dropped requests due to rate-limiting, per team_id, scope and route.",
    labelnames=[LABEL_TEAM_ID, "scope", LABEL_PATH, LABEL_ROUTE],
)

RATE_LIMIT_BYPASSED_COUNTER = Counter(
    "rate_limit_bypassed_total",
    "Requests that should be dropped by rate-limiting but allowed by configuration.",
    labelnames=[LABEL_TEAM_ID, LABEL_PATH, LABEL_ROUTE],
)


@lru_cache(maxsize=1)
def get_team_allow_list(_ttl: int) -> list[str]:
    """
    The "allow list" will change way less frequently than it will be called
    _ttl is passed an infrequently changing value to ensure the cache is invalidated after some delay
    """
    return get_list(get_instance_setting("RATE_LIMITING_ALLOW_LIST_TEAMS"))


def team_is_allowed_to_bypass_throttle(team_id: int | None) -> bool:
    """
    Check if a given team_id belongs to a throttle bypass allow list.
    """
    allow_list = get_team_allow_list(round(time.time() / 60))
    return team_id is not None and str(team_id) in allow_list


@lru_cache(maxsize=1)
def is_rate_limit_enabled(_ttl: int) -> bool:
    """
    The setting will change way less frequently than it will be called
    _ttl is passed an infrequently changing value to ensure the cache is invalidated after some delay
    """
    return get_instance_setting("RATE_LIMIT_ENABLED")


path_by_env_pattern = re.compile(r"^/api/environments/(\d+)/")
path_by_team_pattern = re.compile(r"^/api/projects/(\d+)/")
path_by_org_pattern = re.compile(r"^/api/organizations/(.+?)/")  # .+? is non-greedy match, bit faster here


@patchable
def patchable_resolve(path: str):
    return resolve(path)


route_param_pattern = re.compile(r"/(?:\(.*?<(?:\w+:)?(\w+)>.*?\)|<(?:\w+:)?(\w+)>)(?:/|$)")


def replace_with_param_names(route_pattern):
    """
    Replace matched groups in string with their parameter names from the regex pattern.

    Args:
        string: The input string to process
        pattern: The regex pattern with named groups

    Returns:
        String with matched parts replaced by parameter names
    """

    def extract_param_name(m):
        param = m.group(1) or m.group(2)
        if param.startswith("parent_lookup_"):
            param = param[len("parent_lookup_") :]
        if param == "organization_id":
            return "ORG_ID"
        if param == "project_id" or param == "environment_id":
            return "TEAM_ID"
        return param.upper()

    # Convert Django URL parameter syntax to a label-friendly format
    # e.g., "<team_id>" becomes "TEAM_ID
    route_id = route_param_pattern.sub(lambda m: "/" + extract_param_name(m) + "/", route_pattern)
    if route_id.startswith("^"):
        route_id = route_id[1:]
    if route_id.startswith("api/"):
        route_id = "/" + route_id
    if route_id.endswith("$"):
        route_id = route_id[:-1]
    if route_id.endswith("?"):
        route_id = route_id[:-1]
    return route_id


def get_route_from_path(path: str | None) -> str:
    """
    Extract a generic route identifier from a request path to avoid high cardinality
    in metrics. This uses Django's URL resolver to get the actual route pattern
    and normalizes parameter names for use as metric labels.
    """
    if not path:
        return ""

    with suppress(Exception):
        resolved = patchable_resolve(path)
        route_pattern = resolved.route
        if route_pattern:
            return replace_with_param_names(route_pattern)

    route_id = path_by_env_pattern.sub("/api/environments/TEAM_ID/", path)
    route_id = path_by_team_pattern.sub("/api/projects/TEAM_ID/", route_id)
    return path_by_org_pattern.sub("/api/organizations/ORG_ID/", route_id)


class PersonalApiKeyRateThrottle(SimpleRateThrottle):
    @staticmethod
    def safely_get_team_id_from_view(view):
        """
        Gets the team_id from a view without throwing.

        Not all views have a team_id (e.g. the /organization endpoints),
        and accessing it when it does not exist throws a KeyError. Hence, this method.
        """
        try:
            return getattr(view, "team_id", None)
        except KeyError:
            return None

    def load_team_rate_limit(self, team_id):
        # try loading from cache
        rate_limit_cache_key = f"team_ratelimit_{self.scope}_{team_id}"
        cached_rate_limit = self.cache.get(rate_limit_cache_key, None)
        if cached_rate_limit is not None:
            self.rate = cached_rate_limit
        else:
            team = Team.objects.get(id=team_id)
            if not team or not team.api_query_rate_limit:
                return
            self.rate = team.api_query_rate_limit
            self.cache.set(rate_limit_cache_key, self.rate)

        self.num_requests, self.duration = self.parse_rate(self.rate)

    def allow_request(self, request, view):
        if not is_rate_limit_enabled(round(time.time() / 60)):
            return True

        # Only rate limit authenticated requests made with a personal API key
        personal_api_key = PersonalAPIKeyAuthentication.find_key_with_source(request)
        if request.user.is_authenticated and personal_api_key is None:
            return True

        try:
            team_id = self.safely_get_team_id_from_view(view)
            if team_id is not None and self.scope == HogQLQueryThrottle.scope:
                self.load_team_rate_limit(team_id)

            request_would_be_allowed = super().allow_request(request, view)
            if request_would_be_allowed:
                return True

            path = getattr(request, "path", None)
            route = get_route_from_path(path)

            if team_is_allowed_to_bypass_throttle(team_id):
                statsd.incr(
                    "team_allowed_to_bypass_rate_limit_exceeded",
                    tags={"team_id": team_id, "route": route},
                )
                RATE_LIMIT_BYPASSED_COUNTER.labels(team_id=team_id, path=route, route=route).inc()

                from posthog.clickhouse.query_tagging import tag_queries

                tag_queries(rate_limit_bypass=1)
                return True
            else:
                scope = getattr(self, "scope", None)
                rate = getattr(self, "rate", None)

                statsd.incr(
                    "rate_limit_exceeded",
                    tags={
                        "team_id": team_id,
                        "scope": scope,
                        "rate": rate,
                        "route": route,
                        "hashed_personal_api_key": hash_key_value(personal_api_key[0]) if personal_api_key else None,
                    },
                )
                RATE_LIMIT_EXCEEDED_COUNTER.labels(team_id=team_id, scope=scope, path=route, route=route).inc()

            return False
        except Team.DoesNotExist as e:
            capture_exception(e)
            return False
        except Exception as e:
            capture_exception(e)
            return True

    def get_cache_key(self, request, view):
        """
        Tries the following options in order:
        - personal_api_key
        - team_id
        - user_id
        - ip
        """
        ident = None
        if request.user.is_authenticated:
            api_key = PersonalAPIKeyAuthentication.find_key_with_source(request)
            if api_key is not None:
                ident = hash_key_value(api_key[0])
            else:
                try:
                    team_id = self.safely_get_team_id_from_view(view)
                    if team_id:
                        ident = team_id
                    else:
                        ident = request.user.pk
                except Exception as e:
                    capture_exception(e)
                    ident = self.get_ident(request)
        else:
            ident = self.get_ident(request)

        return self.cache_format % {"scope": self.scope, "ident": ident}


class UserOrEmailRateThrottle(SimpleRateThrottle):
    """
    Typically throttling is on the user or the IP address.
    For unauthenticated signup/login requests we want to throttle on the email address.
    """

    scope = "user"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            # For unauthenticated requests, we want to throttle on something unique to the user they are trying to work with
            # This could be email for example when logging in or uuid when verifying email
            ident = request.data.get("email") or request.data.get("uuid") or self.get_ident(request)
            ident = hashlib.sha256(ident.encode()).hexdigest()

        return self.cache_format % {"scope": self.scope, "ident": ident}

    def parse_rate(self, rate):
        """
        Support custom duration formats like "6/20minutes"
        """
        if rate is None:
            return (None, None)

        num, period = rate.split("/")
        num_requests = int(num)

        if period.endswith("minutes"):
            minutes = int(period[:-7])
            duration = minutes * 60
        else:
            # Fall back to default
            num_requests, duration = super().parse_rate(rate)  # type: ignore

        return (num_requests, duration)


class IPThrottle(SimpleRateThrottle):
    """
    Rate limit requests by IP address.
    This is a general purpose throttle that can be used to rate limit any endpoint by IP address.
    You should subclass this and set the rate and scope.
    """

    def get_cache_key(self, request, view):
        from posthog.utils import get_ip_address

        ip = get_ip_address(request)
        return self.cache_format % {"scope": self.scope, "ident": ip}


class SignupIPThrottle(IPThrottle):
    """
    Rate limit signups by IP address to avoid a single IP address from creating too many accounts.
    """

    scope = "signup_ip"
    rate = "5/day"


class WebAuthnSignupRegistrationThrottle(IPThrottle):
    """
    Rate limit passkey signup registrations by IP address to avoid a single IP address from initiating too many signups.

    Note: this is effectively 5 attempts per minute, because each attempt issues 2 requests: begin, complete.
    """

    scope = "webauthn_signup_registration_ip"
    rate = "10/minute"


class SignupEmailPrecheckThrottle(IPThrottle):
    """
    Rate limit signup email precheck requests by IP.
    """

    scope = "signup_email_precheck"
    rate = "30/minute"


class OnboardingIPThrottle(IPThrottle):
    """
    Rate limit onboarding product recommendations by IP address.
    This endpoint uses an LLM, so we want to be conservative with rate limits.
    """

    scope = "onboarding_ip"
    rate = "10/hour"


class BurstRateThrottle(PersonalApiKeyRateThrottle):
    # Throttle class that's applied on all endpoints (except for capture + decide)
    # Intended to block quick bursts of requests, per project
    scope = "burst"
    rate = "480/minute"


class SustainedRateThrottle(PersonalApiKeyRateThrottle):
    # Throttle class that's applied on all endpoints (except for capture + decide)
    # Intended to block slower but sustained bursts of requests, per project
    scope = "sustained"
    rate = "4800/hour"


class ClickHouseBurstRateThrottle(PersonalApiKeyRateThrottle):
    # Throttle class that's a bit more aggressive and is used specifically on endpoints that hit ClickHouse
    # Intended to block quick bursts of requests, per project
    scope = "clickhouse_burst"
    rate = "240/minute"


class ClickHouseSustainedRateThrottle(PersonalApiKeyRateThrottle):
    # Throttle class that's a bit more aggressive and is used specifically on endpoints that hit ClickHouse
    # Intended to block slower but sustained bursts of requests, per project
    scope = "clickhouse_sustained"
    rate = "1200/hour"


class AIBurstRateThrottle(UserRateThrottle):
    # Throttle class that's very aggressive and is used specifically on endpoints that hit OpenAI
    # Intended to block quick bursts of requests, per user
    scope = "ai_burst"
    rate = "10/minute"

    def allow_request(self, request, view):
        request_allowed = super().allow_request(request, view)

        if not request_allowed and request.user.is_authenticated:
            report_user_action(request.user, "ai burst rate limited")

        return request_allowed


class AISustainedRateThrottle(UserRateThrottle):
    # Throttle class that's very aggressive and is used specifically on endpoints that hit OpenAI
    # Intended to block slower but sustained bursts of requests, per user
    scope = "ai_sustained"
    rate = "100/day"

    def allow_request(self, request, view):
        request_allowed = super().allow_request(request, view)

        if not request_allowed and request.user.is_authenticated:
            report_user_action(request.user, "ai sustained rate limited")

        return request_allowed


class LLMProxyBurstRateThrottle(UserRateThrottle):
    scope = "llm_proxy_burst"
    rate = "2/minute"


class LLMProxySustainedRateThrottle(UserRateThrottle):
    scope = "llm_proxy_sustained"
    rate = "10/hour"


class LLMProxyDailyRateThrottle(UserRateThrottle):
    scope = "llm_proxy_daily"
    rate = "20/day"


class HogQLQueryThrottle(PersonalApiKeyRateThrottle):
    # Lower rate limit for HogQL queries
    scope = "query"
    rate = "120/hour"


class APIQueriesBurstThrottle(PersonalApiKeyRateThrottle):
    scope = "api_queries_burst"
    rate = "240/minute"


class APIQueriesSustainedThrottle(PersonalApiKeyRateThrottle):
    scope = "api_queries_sustained"
    rate = "2400/hour"


class WebAnalyticsAPIBurstThrottle(PersonalApiKeyRateThrottle):
    scope = "web_analytics_api_burst"
    rate = "240/minute"


class WebAnalyticsAPISustainedThrottle(PersonalApiKeyRateThrottle):
    scope = "web_analytics_api_sustained"
    rate = "2400/hour"


class LLMAnalyticsTextReprBurstThrottle(PersonalApiKeyRateThrottle):
    scope = "llm_analytics_text_repr_burst"
    rate = "120/minute"


class LLMAnalyticsTextReprSustainedThrottle(PersonalApiKeyRateThrottle):
    scope = "llm_analytics_text_repr_sustained"
    rate = "600/hour"


class LLMAnalyticsTranslationBurstThrottle(PersonalApiKeyRateThrottle):
    scope = "llm_analytics_translation_burst"
    rate = "30/minute"


class LLMAnalyticsTranslationSustainedThrottle(PersonalApiKeyRateThrottle):
    scope = "llm_analytics_translation_sustained"
    rate = "200/hour"


class LLMAnalyticsTranslationDailyThrottle(PersonalApiKeyRateThrottle):
    # Daily cap for LLM-powered translation endpoint
    # Hard limit to prevent runaway costs
    scope = "llm_analytics_translation_daily"
    rate = "500/day"


class LLMAnalyticsSummarizationBurstThrottle(PersonalApiKeyRateThrottle):
    # Rate limit for LLM-powered summarization endpoint
    # Conservative limits to control OpenAI API costs
    scope = "llm_analytics_summarization_burst"
    rate = "50/minute"


class LLMAnalyticsSummarizationSustainedThrottle(PersonalApiKeyRateThrottle):
    # Rate limit for LLM-powered summarization endpoint
    # Conservative limits to control OpenAI API costs
    scope = "llm_analytics_summarization_sustained"
    rate = "200/hour"


class LLMAnalyticsSummarizationDailyThrottle(PersonalApiKeyRateThrottle):
    # Daily cap for LLM-powered summarization endpoint
    # Hard limit to prevent runaway costs
    scope = "llm_analytics_summarization_daily"
    rate = "500/day"


class UserPasswordResetThrottle(UserOrEmailRateThrottle):
    scope = "user_password_reset"
    rate = "6/day"


class EmailMFAThrottle(UserOrEmailRateThrottle):
    scope = "email_mfa"
    rate = "6/20minutes"


class EmailMFAResendThrottle(UserOrEmailRateThrottle):
    scope = "email_mfa_resend"
    rate = "1/minute"

    def get_cache_key(self, request, view):
        from posthog.helpers.two_factor_session import email_mfa_verifier

        user_id = email_mfa_verifier.get_pending_email_mfa_verification_user_id(request)
        if user_id:
            ident = hashlib.sha256(str(user_id).encode()).hexdigest()
            return self.cache_format % {"scope": self.scope, "ident": ident}

        return super().get_cache_key(request, view)


class TwoFactorThrottle(UserOrEmailRateThrottle):
    """
    Rate limiting for TOTP/backup code verification during 2FA login.
    Uses the pending 2FA user ID from session to throttle per-user.
    """

    scope = "two_factor"
    rate = "6/20minutes"

    def get_cache_key(self, request, view):
        user_id = request.session.get("user_authenticated_but_no_2fa")
        if user_id:
            ident = hashlib.sha256(str(user_id).encode()).hexdigest()
            return self.cache_format % {"scope": self.scope, "ident": ident}

        return super().get_cache_key(request, view)


class UserAuthenticationThrottle(UserOrEmailRateThrottle):
    scope = "user_authentication"
    rate = "5/minute"

    def allow_request(self, request, view):
        # only throttle non-GET requests
        if request.method == "GET":
            return True

        # only throttle if attempting to change current password
        if "current_password" not in request.data:
            return True

        return super().allow_request(request, view)


class UserEmailVerificationThrottle(UserOrEmailRateThrottle):
    scope = "user_email_verification"
    rate = "6/day"


class SetupWizardAuthenticationRateThrottle(UserRateThrottle):
    # Throttle class that is applied for authenticating the setup wizard
    # This is more aggressive than other throttles because the wizard makes LLM calls
    scope = "wizard_authentication"
    rate = "20/day"


class SetupWizardQueryRateThrottle(SimpleRateThrottle):
    def get_rate(self):
        if settings.DEBUG:
            return "1000/day"
        return "20/day"

    # Throttle per wizard hash
    def get_cache_key(self, request, view):
        hash = request.headers.get("X-PostHog-Wizard-Hash")

        authorization_header = request.headers.get("Authorization")

        value = (hash or authorization_header or "").strip() or self.get_ident(request)

        sha_hash = hashlib.sha256(value.encode()).hexdigest()

        # this value isn't use controllable and can't generate html/js, so there's no risk of xss
        # nosemgrep: python.flask.security.audit.directly-returned-format-string.directly-returned-format-string
        return f"throttle_wizard_query_{sha_hash}"


class SymbolSetUploadBurstRateThrottle(PersonalApiKeyRateThrottle):
    scope = "symbol_set_upload_burst"
    rate = "1200/minute"


class BreakGlassSustainedThrottle(UserOrEmailRateThrottle):
    # Throttle class that can be applied when a bug is causing too many requests to hit and an endpoint, e.g. a bug in the frontend hitting an endpoint in a loop
    # Prefer making a subclass of this for specific endpoints, and setting a scope
    rate = "75/hour"


class WidgetUserBurstThrottle(SimpleRateThrottle):
    """Rate limit per widget_session_id or IP for POST/GET requests."""

    scope = "widget_user_burst"
    rate = "30/minute"

    def get_cache_key(self, request, view):
        # Throttle by widget_session_id if available, otherwise by IP
        widget_session_id = request.data.get("widget_session_id") or request.query_params.get("widget_session_id")
        if widget_session_id:
            ident = hashlib.sha256(widget_session_id.encode()).hexdigest()
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class WidgetTeamThrottle(SimpleRateThrottle):
    """Rate limit per team token."""

    scope = "widget_team"
    rate = "1000/hour"

    def get_cache_key(self, request, view):
        # Throttle by team token if available, otherwise by IP
        token = request.headers.get("X-Conversations-Token", "")
        if token:
            ident = hashlib.sha256(token.encode()).hexdigest()
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class SymbolSetUploadSustainedRateThrottle(PersonalApiKeyRateThrottle):
    scope = "symbol_set_upload_sustained"
    rate = "12000/hour"
