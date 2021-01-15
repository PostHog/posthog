import json
import secrets
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.models import Team, User
from posthog.models.feature_flag import get_active_feature_flags
from posthog.utils import cors_response, load_data_from_request

from .capture import _get_project_id, _get_token


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
            data = data_from_request["data"]
        except (json.decoder.JSONDecodeError, TypeError):
            return cors_response(
                request,
                JsonResponse(
                    {"code": "validation", "message": "Malformed request data. Make sure you're sending valid JSON.",},
                    status=400,
                ),
            )
        token = _get_token(data, request)
        team = Team.objects.get_team_from_token(token)
        if team is None and token:
            project_id = _get_project_id(data, request)
            user = User.objects.get_from_personal_api_key(token)
            if user is None:
                return cors_response(
                    request, JsonResponse({"code": "validation", "message": "Invalid personal API key.",}, status=400,),
                )
            team = user.teams.get(id=project_id)
        if team:
            response["featureFlags"] = get_active_feature_flags(team, data_from_request["data"]["distinct_id"])
            if team.session_recording_opt_in and (on_permitted_domain(team, request) or len(team.app_urls) == 0):
                response["sessionRecording"] = {"endpoint": "/s/"}
    return cors_response(request, JsonResponse(response))
