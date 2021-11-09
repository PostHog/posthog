import re
import secrets
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.api.utils import get_token
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.models import Team, User
from posthog.models.feature_flag import get_overridden_feature_flags
from posthog.utils import cors_response, load_data_from_request

from .utils import get_project_id


def on_permitted_domain(team: Team, request: HttpRequest) -> bool:
    permitted_domains = ["127.0.0.1", "localhost"]

    for url in team.app_urls:
        hostname = parse_domain(url)
        if hostname:
            permitted_domains.append(hostname)

    origin = parse_domain(request.headers.get("Origin"))
    referer = parse_domain(request.headers.get("Referer"))
    for permitted_domain in permitted_domains:
        if "*" in permitted_domain:
            pattern = "^{}$".format(permitted_domain.replace(".", "\\.").replace("*", "(.*)"))
            if (origin and re.search(pattern, origin)) or (referer and re.search(pattern, referer)):
                return True
        else:
            if permitted_domain == origin or permitted_domain == referer:
                return True
    return False


def decide_editor_params(request: HttpRequest) -> Tuple[Dict[str, Any], bool]:
    if request.user.is_anonymous:
        return {}, False

    team = request.user.team
    if team and on_permitted_domain(team, request):
        response: Dict[str, Any] = {"isAuthenticated": True}
        editor_params = {}

        if request.user.toolbar_mode != "disabled":
            editor_params["toolbarVersion"] = "toolbar"

        if settings.JS_URL:
            editor_params["jsURL"] = settings.JS_URL

        response["editorParams"] = editor_params
        return response, not request.user.temporary_token
    else:
        return {}, False


def parse_domain(url: Any) -> Optional[str]:
    return urlparse(url).hostname


@csrf_exempt
def get_decide(request: HttpRequest):
    response = {
        "config": {"enable_collect_everything": True},
        "editorParams": {},
        "isAuthenticated": False,
        "supportedCompression": ["gzip", "gzip-js", "lz64"],
    }

    if request.COOKIES.get(settings.TOOLBAR_COOKIE_NAME) and request.user.is_authenticated:
        response["isAuthenticated"] = True
        if settings.JS_URL and request.user.toolbar_mode == User.TOOLBAR:
            response["editorParams"] = {"jsURL": settings.JS_URL, "toolbarVersion": "toolbar"}

    if request.user.is_authenticated:
        r, update_user_token = decide_editor_params(request)
        response.update(r)
        if update_user_token:
            request.user.temporary_token = secrets.token_urlsafe(32)
            request.user.save()

    response["featureFlags"] = []
    response["sessionRecording"] = False

    if request.method == "POST":
        try:
            data = load_data_from_request(request)
            api_version_string = request.GET.get("v")
            # NOTE: This does not support semantic versioning e.g. 2.1.0
            api_version = int(api_version_string) if api_version_string else 1
        except (RequestParsingError, ValueError) as error:
            capture_exception(error)  # We still capture this on Sentry to identify actual potential bugs
            return cors_response(
                request,
                generate_exception_response("decide", f"Malformed request data: {error}", code="malformed_data"),
            )

        token = get_token(data, request)
        team = Team.objects.get_team_from_token(token)
        if team is None and token:
            project_id = get_project_id(data, request)

            if not project_id:
                return cors_response(
                    request,
                    generate_exception_response(
                        "decide",
                        "Project API key invalid. You can find your project API key in PostHog project settings.",
                        code="invalid_api_key",
                        type="authentication_error",
                        status_code=status.HTTP_401_UNAUTHORIZED,
                    ),
                )

            user = User.objects.get_from_personal_api_key(token)
            if user is None:
                return cors_response(
                    request,
                    generate_exception_response(
                        "decide",
                        "Invalid Personal API key.",
                        code="invalid_personal_key",
                        type="authentication_error",
                        status_code=status.HTTP_401_UNAUTHORIZED,
                    ),
                )
            team = user.teams.get(id=project_id)

        if team:
            feature_flags = get_overridden_feature_flags(team, data["distinct_id"])
            response["featureFlags"] = feature_flags if api_version >= 2 else list(feature_flags.keys())

            if team.session_recording_opt_in and (on_permitted_domain(team, request) or len(team.app_urls) == 0):
                response["sessionRecording"] = {"endpoint": "/s/"}
    statsd.incr(
        f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "decide",},
    )
    return cors_response(request, JsonResponse(response))
