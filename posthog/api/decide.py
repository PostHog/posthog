import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.api.utils import get_token
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.logging.timing import timed
from posthog.models import Team, User
from posthog.models.feature_flag import get_active_feature_flags
from posthog.utils import cors_response, get_js_url, load_data_from_request

from .utils import get_project_id


def on_permitted_domain(team: Team, request: HttpRequest) -> bool:
    origin = parse_domain(request.headers.get("Origin"))
    referer = parse_domain(request.headers.get("Referer"))
    return hostname_in_app_urls(team, origin) or hostname_in_app_urls(team, referer)


def hostname_in_app_urls(team: Team, hostname: Optional[str]) -> bool:
    if not hostname:
        return False

    permitted_domains = ["127.0.0.1", "localhost"]

    for url in team.app_urls:
        host = parse_domain(url)
        if host:
            permitted_domains.append(host)

    for permitted_domain in permitted_domains:
        if "*" in permitted_domain:
            pattern = "^{}$".format(re.escape(permitted_domain).replace("\\*", "(.*)"))
            if re.search(pattern, hostname):
                return True
        elif permitted_domain == hostname:
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

        if get_js_url(request):
            editor_params["jsURL"] = get_js_url(request)

        response["editorParams"] = editor_params
        return response, not request.user.temporary_token
    else:
        return {}, False


def parse_domain(url: Any) -> Optional[str]:
    return urlparse(url).hostname


@csrf_exempt
@timed("posthog_cloud_decide_endpoint")
def get_decide(request: HttpRequest):
    # handle cors request
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": 1}))

    response = {
        "config": {"enable_collect_everything": True},
        "editorParams": {},
        "isAuthenticated": False,
        "supportedCompression": ["gzip", "gzip-js", "lz64"],
    }

    response["featureFlags"] = []
    response["sessionRecording"] = False

    if request.method == "POST":
        try:
            data = load_data_from_request(request)
            api_version_string = request.GET.get("v")
            # NOTE: This does not support semantic versioning e.g. 2.1.0
            api_version = int(api_version_string) if api_version_string else 1
        except ValueError:
            # default value added because of bug in posthog-js 1.19.0
            # see https://sentry.io/organizations/posthog2/issues/2738865125/?project=1899813
            # as a tombstone if the below statsd counter hasn't seen errors for N days
            # then it is likely that no clients are running posthog-js 1.19.0
            # and this defaulting could be removed
            statsd.incr(
                f"posthog_cloud_decide_defaulted_api_version_on_value_error",
                tags={"endpoint": "decide", "api_version_string": api_version_string},
            )
            api_version = 2
        except RequestParsingError as error:
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
            distinct_id = data.get("distinct_id")
            if distinct_id is None:
                return cors_response(
                    request,
                    generate_exception_response(
                        "decide",
                        "Decide requires a distinct_id.",
                        code="missing_distinct_id",
                        type="validation_error",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    ),
                )
            feature_flags = get_active_feature_flags(
                team.pk, distinct_id, data.get("groups", {}), hash_key_override=data.get("$anon_distinct_id")
            )
            response["featureFlags"] = feature_flags if api_version >= 2 else list(feature_flags.keys())

            if team.session_recording_opt_in and (on_permitted_domain(team, request) or len(team.app_urls) == 0):
                response["sessionRecording"] = {"endpoint": "/s/"}
    statsd.incr(
        f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "decide",},
    )
    return cors_response(request, JsonResponse(response))
