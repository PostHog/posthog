import base64
import gzip
import json
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import lzstring  # type: ignore
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from posthog.models import FeatureFlag, Team
from posthog.utils import cors_response


def _load_data(request) -> Optional[Dict[str, Any]]:
    # JS Integration reloadFeatureFlags call
    if request.content_type == "application/x-www-form-urlencoded":
        return _base64_to_json(request.POST["data"])

    if request.content_type == "application/json":
        data = request.body
    else:
        data = request.POST.get("data")

    if not data:
        return None

    compression = (
        request.GET.get("compression") or request.POST.get("compression") or request.headers.get("content-encoding", "")
    )
    compression = compression.lower()

    if compression == "gzip":
        data = gzip.decompress(data)

    if compression == "lz64":
        if isinstance(data, str):
            data = lzstring.LZString().decompressFromBase64(data.replace(" ", "+"))
        else:
            data = lzstring.LZString().decompressFromBase64(data.decode().replace(" ", "+"))

    #  Is it plain json?
    try:
        data = json.loads(data)
    except json.JSONDecodeError:
        # if not, it's probably base64 encoded from other libraries
        data = _base64_to_json(data)

    # FIXME: data can also be an array, function assumes it's either None or a dictionary.
    return data


def _base64_to_json(data) -> Dict:
    return json.loads(
        base64.b64decode(data.replace(" ", "+") + "===")
        .decode("utf8", "surrogatepass")
        .encode("utf-16", "surrogatepass")
    )


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


def feature_flags(request: HttpRequest) -> List[str]:
    if request.method != "POST":
        return []
    data = _load_data(request)
    if not data:
        return []
    token = _get_token(data, request)
    team = Team.objects.get_cached_from_token(token)
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

    response["featureFlags"] = feature_flags(request)
    return cors_response(request, JsonResponse(response))
