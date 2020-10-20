import json
import secrets
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models import FeatureFlag, Team
from posthog.utils import base64_to_json, cors_response, load_data_from_request


def _get_token(data, request):
    if request.POST.get("api_key"):
        return request.POST["api_key"]
    if request.POST.get("token"):
        return request.POST["token"]
    if "token" in data:
        return data["token"]  # JS reloadFeatures call
    if "api_key" in data:
        return data["api_key"]  # server-side libraries like posthog-python and posthog-ruby
    return None


def on_permitted_domain(team: Team, request: HttpRequest) -> bool:
    permitted_domains = ["127.0.0.1", "localhost"]

    for url in team.app_urls:
        hostname = parse_domain(url)
        if hostname:
            permitted_domains.append(hostname)

    return (parse_domain(request.headers.get("Origin")) in permitted_domains) or (
        parse_domain(request.headers.get("Referer")) in permitted_domains
    )


def decide_editor_params(request: HttpRequest) -> Tuple[Dict[str, Any], bool]:
    if on_permitted_domain(request.user.team, request):
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


# May raise exception if request body is malformed
def get_team_from_token(request: HttpRequest, data_from_request: Dict[str, Any]) -> Union[Team, None]:
    data = data_from_request["data"]
    if not data:
        return None

    token = _get_token(data, request)
    is_personal_api_key = False
    if not token:
        token = PersonalAPIKeyAuthentication.find_key(
            request, data_from_request["body"], data if isinstance(data, dict) else None
        )
        is_personal_api_key = True

    if token:
        return Team.objects.get_team_from_token(token, is_personal_api_key)

    return None


def feature_flags(request: HttpRequest, team: Team, data: Dict[str, Any]) -> List[str]:
    flags_enabled = []
    feature_flags = FeatureFlag.objects.filter(team=team, active=True, deleted=False)
    for feature_flag in feature_flags:
        # distinct_id will always be a string, but data can have non-string values ("Any")
        if feature_flag.distinct_id_matches(data["distinct_id"]):
            flags_enabled.append(feature_flag.key)
    return flags_enabled


def parse_domain(url: Any) -> Optional[str]:
    return urlparse(url).hostname


@csrf_exempt
def get_decide(request: HttpRequest):
    response = {
        "config": {"enable_collect_everything": True},
        "editorParams": {},
        "isAuthenticated": False,
        "supportedCompression": ["gzip", "lz64"],
    }

    if request.COOKIES.get(settings.TOOLBAR_COOKIE_NAME):
        response["isAuthenticated"] = True
        if settings.JS_URL:
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
            data_from_request = load_data_from_request(request)
        except (json.decoder.JSONDecodeError, TypeError):
            return cors_response(
                request,
                JsonResponse(
                    {"code": "validation", "message": "Malformed request data. Make sure you're sending valid JSON.",},
                    status=400,
                ),
            )

        team = get_team_from_token(request, data_from_request)
        if team:
            response["featureFlags"] = feature_flags(request, team, data_from_request["data"])
            response["sessionRecording"] = team.session_recording_opt_in and on_permitted_domain(team, request)
    return cors_response(request, JsonResponse(response))
