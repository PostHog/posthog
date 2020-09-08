import json
import secrets
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.models import FeatureFlag, Team
from posthog.utils import PersonalAPIKeyAuthentication, base64_to_json, cors_response, load_data_from_request


def _load_data(request) -> Optional[Union[Dict[str, Any], List]]:
    # JS Integration reloadFeatureFlags call
    if request.content_type == "application/x-www-form-urlencoded":
        return base64_to_json(request.POST["data"])

    return load_data_from_request(request)


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


def feature_flags(request: HttpRequest) -> Dict[str, Any]:
    feature_flags_data = {"flags_enabled": [], "has_malformed_json": False}
    try:
        data_from_request = load_data_from_request(request)
        data = data_from_request["data"]
    except (json.decoder.JSONDecodeError, TypeError):
        feature_flags_data["has_malformed_json"] = True
        return feature_flags_data

    if not data:
        return feature_flags_data

    token = _get_token(data, request)
    is_personal_api_key = False
    if not token:
        token = PersonalAPIKeyAuthentication.find_key(
            request, data_from_request["body"], data if isinstance(data, dict) else None
        )
        is_personal_api_key = True
    if not token:
        return feature_flags_data
    team = Team.objects.get_cached_from_token(token, is_personal_api_key)
    flags_enabled = []
    feature_flags = FeatureFlag.objects.filter(team=team, active=True, deleted=False)
    for feature_flag in feature_flags:
        # distinct_id will always be a string, but data can have non-string values ("Any")
        if feature_flag.distinct_id_matches(data["distinct_id"]):
            flags_enabled.append(feature_flag.key)
    feature_flags_data["flags_enabled"] = flags_enabled
    return feature_flags_data


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
        team = request.user.team_set.get()
        permitted_domains = ["127.0.0.1", "localhost"]

        for url in team.app_urls:
            hostname = parse_domain(url)
            if hostname:
                permitted_domains.append(hostname)

        if (parse_domain(request.headers.get("Origin")) in permitted_domains) or (
            parse_domain(request.headers.get("Referer")) in permitted_domains
        ):
            response["isAuthenticated"] = True
            editor_params = {}

            if request.user.toolbar_mode == "toolbar":
                editor_params["toolbarVersion"] = "toolbar"

            if settings.JS_URL:
                editor_params["jsURL"] = settings.JS_URL

            response["editorParams"] = editor_params

            if not request.user.temporary_token:
                request.user.temporary_token = secrets.token_urlsafe(32)
                request.user.save()
    response["featureFlags"] = []
    if request.method == "POST":
        feature_flags_data = feature_flags(request)
        if feature_flags_data["has_malformed_json"]:
            return cors_response(
                request,
                JsonResponse(
                    {"code": "validation", "message": "Malformed request data. Make sure you're sending valid JSON.",},
                    status=400,
                ),
            )
        response["featureFlags"] = feature_flags_data["flags_enabled"]
    return cors_response(request, JsonResponse(response))
