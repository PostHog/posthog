from django.conf import settings
from django.http import JsonResponse, HttpRequest
from django.views.decorators.csrf import csrf_exempt
from typing import Optional, List, Any, Dict
from posthog.utils import cors_response
from urllib.parse import urlparse
from posthog.models import FeatureFlag, Team
import json
import base64
import secrets


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
    }

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

            if request.user.toolbar_mode == 'toolbar':
                editor_params['toolbarVersion'] = 'toolbar'

            if settings.DEBUG:
                editor_params["jsURL"] = "http://localhost:8234/"

            response["editorParams"] = editor_params

            if not request.user.temporary_token:
                request.user.temporary_token = secrets.token_urlsafe(32)
                request.user.save()

    response["featureFlags"] = feature_flags(request)
    return cors_response(request, JsonResponse(response))
