import base64
import json
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.models import FeatureFlag, Team
from posthog.utils import cors_response


def _load_data(data: str) -> Dict[str, Any]:
    return json.loads(
        base64.b64decode(data.replace(" ", "+") + "===")
        .decode("utf8", "surrogatepass")
        .encode("utf-16", "surrogatepass")
    )


def feature_flags(request: HttpRequest) -> List[str]:
    if request.method != "POST" or not request.POST.get("data"):
        return []

    data = _load_data(request.POST["data"])
    team = Team.objects.get_cached_from_token(data["token"])
    flags_enabled = []

    feature_flags = FeatureFlag.objects.filter(team=team, active=True, deleted=False)
    for feature_flag in feature_flags:
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

    if request.method == "POST":
        try:
            _load_data(request.POST["data"])
        except json.decoder.JSONDecodeError:
            return cors_response(
                request,
                JsonResponse(
                    {"code": "validation", "message": "Malformed request data. Make sure you're sending valid JSON.",},
                    status=400,
                ),
            )

    response["featureFlags"] = feature_flags(request)
    return cors_response(request, JsonResponse(response))
