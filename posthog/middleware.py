from ipaddress import ip_address, ip_network
from typing import List, Optional, cast

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import MiddlewareNotUsed
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.cache import add_never_cache_headers

from posthog.models import Action, Cohort, Dashboard, FeatureFlag, Insight, User
from posthog.models.team import Team

from .auth import PersonalAPIKeyAuthentication


class AllowIPMiddleware:
    trusted_proxies: List[str] = []

    def __init__(self, get_response):
        if not settings.ALLOWED_IP_BLOCKS:
            # this will make Django skip this middleware for all future requests
            raise MiddlewareNotUsed()
        self.ip_blocks = settings.ALLOWED_IP_BLOCKS

        if settings.TRUSTED_PROXIES:
            self.trusted_proxies = [item.strip() for item in settings.TRUSTED_PROXIES.split(",")]
        self.get_response = get_response

    def get_forwarded_for(self, request: HttpRequest):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for is not None:
            return [ip.strip() for ip in forwarded_for.split(",")]
        else:
            return []

    def extract_client_ip(self, request: HttpRequest):
        client_ip = request.META["REMOTE_ADDR"]
        if getattr(settings, "USE_X_FORWARDED_HOST", False):
            forwarded_for = self.get_forwarded_for(request)
            if forwarded_for:
                closest_proxy = client_ip
                client_ip = forwarded_for.pop(0)
                if settings.TRUST_ALL_PROXIES:
                    return client_ip
                proxies = [closest_proxy] + forwarded_for
                for proxy in proxies:
                    if proxy not in self.trusted_proxies:
                        return None
        return client_ip

    def __call__(self, request: HttpRequest):
        response: HttpResponse = self.get_response(request)
        if request.path.split("/")[1] in [
            "decide",
            "engage",
            "track",
            "capture",
            "batch",
            "e",
            "static",
            "_health",
        ]:
            return response
        ip = self.extract_client_ip(request)
        if ip and any(ip_address(ip) in ip_network(block, strict=False) for block in self.ip_blocks):
            return response
        return HttpResponse(
            "Your IP is not allowed. Check your ALLOWED_IP_BLOCKS settings. If you are behind a proxy, you need to set TRUSTED_PROXIES. See https://posthog.com/docs/deployment/running-behind-proxy",
            status=403,
        )


class ToolbarCookieMiddleware(SessionMiddleware):
    def process_response(self, request, response):
        response = super().process_response(request, response)

        # skip adding the toolbar 3rd party cookie on API requests
        if request.path.startswith("/api/") or request.path.startswith("/e/") or request.path.startswith("/decide/"):
            return response

        toolbar_cookie_name = settings.TOOLBAR_COOKIE_NAME  # type: str
        toolbar_cookie_secure = settings.TOOLBAR_COOKIE_SECURE  # type: bool

        if (
            toolbar_cookie_name not in response.cookies
            and request.user
            and request.user.is_authenticated
            and request.user.toolbar_mode != "disabled"
        ):
            response.set_cookie(
                toolbar_cookie_name,  # key
                "yes",  # value
                365 * 24 * 60 * 60,  # max_age = one year
                None,  # expires
                "/",  # path
                None,  # domain
                toolbar_cookie_secure,  # secure
                True,  # httponly
                "Lax",  # samesite, can't be set to "None" here :(
            )
            response.cookies[toolbar_cookie_name]["samesite"] = "None"  # must set explicitly

        return response


class CsrfOrKeyViewMiddleware(CsrfViewMiddleware):
    """Middleware accepting requests that either contain a valid CSRF token or a personal API key."""

    def process_view(self, request, callback, callback_args, callback_kwargs):
        result = super().process_view(request, callback, callback_args, callback_kwargs)  # None if request accepted
        # if super().process_view did not find a valid CSRF token, try looking for a personal API key
        if result is not None and PersonalAPIKeyAuthentication.find_key_with_source(request) is not None:
            return self._accept(request)
        return result

    def _accept(self, request):
        request.csrf_processing_done = True
        return None


# Work around cloudflare by default caching csv files
class CsvNeverCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.endswith("csv"):
            add_never_cache_headers(response)
        return response


class AutoProjectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        target_queryset = self.get_target_queryset(request)
        if target_queryset is not None:
            user = cast(User, request.user)
            current_team = user.team
            if current_team is not None and not target_queryset.filter(team=current_team).exists():
                item_of_alternative_team = target_queryset.only("team").first()
                actual_item_team: Optional[Team] = item_of_alternative_team.team
                if (
                    actual_item_team is not None
                    and actual_item_team.get_effective_membership_level(user.id) is not None
                ):
                    user.current_team = actual_item_team
                    user.current_organization_id = actual_item_team.organization_id
                    user.save()
                    setattr(request, "preswitch_team_name", current_team.name)  # Context for POSTHOG_APP_CONTEXT
        response = self.get_response(request)
        return response

    def get_target_queryset(self, request: HttpRequest) -> Optional[QuerySet]:
        path_parts = request.path.strip("/").split("/")
        # Sync the paths with urls.ts!
        if len(path_parts) >= 2:
            if path_parts[0] == "dashboard":
                dashboard_id = path_parts[1]
                return Dashboard.objects.filter(deleted=False, id=dashboard_id)
            elif path_parts[0] == "insights":
                insight_short_id = path_parts[1]
                return Insight.objects.filter(deleted=False, short_id=insight_short_id)
            elif path_parts[0] == "feature_flags":
                feature_flag_id = path_parts[1]
                return FeatureFlag.objects.filter(deleted=False, id=feature_flag_id)
            elif path_parts[0] == "action":
                action_id = path_parts[1]
                return Action.objects.filter(deleted=False, id=action_id)
            elif path_parts[0] == "cohorts":
                cohort_id = path_parts[1]
                return Cohort.objects.filter(deleted=False, id=cohort_id)
        return None
