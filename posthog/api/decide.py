import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import structlog
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.api.geoip import get_geoip_properties
from posthog.api.utils import get_project_id, get_token
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.logging.timing import timed
from posthog.models import Team, User
from posthog.models.feature_flag import get_active_feature_flags
from posthog.plugins.site import get_decide_site_apps
from posthog.utils import cors_response, get_ip_address, load_data_from_request


def on_permitted_recording_domain(team: Team, request: HttpRequest) -> bool:
    origin = parse_domain(request.headers.get("Origin"))
    referer = parse_domain(request.headers.get("Referer"))
    return hostname_in_allowed_url_list(team.recording_domains, origin) or hostname_in_allowed_url_list(
        team.recording_domains, referer
    )


def hostname_in_allowed_url_list(allowed_url_list: Optional[List[str]], hostname: Optional[str]) -> bool:
    if not hostname:
        return False

    permitted_domains = ["127.0.0.1", "localhost"]
    if allowed_url_list:
        for url in allowed_url_list:
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
        "toolbarParams": {},
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
            structlog.contextvars.bind_contextvars(team_id=team.id)

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

            property_overrides = get_geoip_properties(get_ip_address(request))
            all_property_overrides: Dict[str, Union[str, int]] = {
                **property_overrides,
                **(data.get("person_properties") or {}),
            }

            feature_flags, _ = get_active_feature_flags(
                team.pk,
                data["distinct_id"],
                data.get("groups") or {},
                hash_key_override=data.get("$anon_distinct_id"),
                property_value_overrides=all_property_overrides,
                group_property_value_overrides=(data.get("group_properties") or {}),
            )
            response["featureFlags"] = feature_flags if api_version >= 2 else list(feature_flags.keys())

            if team.session_recording_opt_in and (
                on_permitted_recording_domain(team, request) or not team.recording_domains
            ):
                capture_console_logs = True if team.capture_console_log_opt_in else False
                response["sessionRecording"] = {"endpoint": "/s/", "consoleLogRecordingEnabled": capture_console_logs}

            response["siteApps"] = get_decide_site_apps(team) if team.inject_web_apps else []

    statsd.incr(f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "decide"})
    return cors_response(request, JsonResponse(response))
