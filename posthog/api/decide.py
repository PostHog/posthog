from random import random
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse
from posthog.models.feature_flag.flag_analytics import increment_request_count
from posthog.models.filters.mixins.utils import process_bool

import structlog
import posthoganalytics
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.api.geoip import get_geoip_properties
from posthog.api.utils import get_project_id, get_token
from posthog.exceptions import RequestParsingError, generate_exception_response
from posthog.logging.timing import timed
from posthog.models import Team, User
from posthog.models.feature_flag import get_all_feature_flags
from posthog.models.utils import execute_with_timeout
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

    permitted_domains = []
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
        # gzip and gzip-js are aliases for the same compression algorithm
        "supportedCompression": ["gzip", "gzip-js"],
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
        team = Team.objects.get_team_from_cache_or_token(token)
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
            else:
                distinct_id = str(distinct_id)

            property_overrides = {}
            geoip_enabled = process_bool(data.get("geoip_disable")) is False

            if geoip_enabled:
                property_overrides = get_geoip_properties(get_ip_address(request))

            all_property_overrides: Dict[str, Union[str, int]] = {
                **property_overrides,
                **(data.get("person_properties") or {}),
            }

            feature_flags, _, feature_flag_payloads, errors = get_all_feature_flags(
                team.pk,
                distinct_id,
                data.get("groups") or {},
                hash_key_override=data.get("$anon_distinct_id"),
                property_value_overrides=all_property_overrides,
                group_property_value_overrides=(data.get("group_properties") or {}),
            )

            active_flags = {key: value for key, value in feature_flags.items() if value}

            if api_version == 2:
                response["featureFlags"] = active_flags
            elif api_version >= 3:
                # v3 returns all flags, not just active ones, as well as if there was an error computing all flags
                response["featureFlags"] = feature_flags
                response["errorsWhileComputingFlags"] = errors
                response["featureFlagPayloads"] = feature_flag_payloads
            else:
                # default v1
                response["featureFlags"] = list(active_flags.keys())

            response["capturePerformance"] = True if team.capture_performance_opt_in else False
            response["autocapture_opt_out"] = True if team.autocapture_opt_out else False
            response["autocaptureExceptions"] = (
                {"endpoint": "/e/", "errors_to_ignore": team.autocapture_exceptions_errors_to_ignore or []}
                if team.autocapture_exceptions_opt_in
                else False
            )

            if team.session_recording_opt_in and (
                on_permitted_recording_domain(team, request) or not team.recording_domains
            ):
                capture_console_logs = True if team.capture_console_log_opt_in else False
                response["sessionRecording"] = {
                    "endpoint": "/s/",
                    "consoleLogRecordingEnabled": capture_console_logs,
                    "recorderVersion": "v2" if team.session_recording_version == "v2" else "v1",
                }

            site_apps = []
            if team.inject_web_apps:
                try:
                    with execute_with_timeout(200):
                        site_apps = get_decide_site_apps(team)
                except Exception:
                    pass

            response["siteApps"] = site_apps

            # NOTE: Whenever you add something to decide response, update this test:
            # `test_decide_doesnt_error_out_when_database_is_down`
            # which ensures that decide doesn't error out when the database is down

            if feature_flags:
                # Billing analytics for decide requests with feature flags

                # Sample no. of decide requests with feature flags
                if settings.DECIDE_BILLING_SAMPLING_RATE and random() < settings.DECIDE_BILLING_SAMPLING_RATE:
                    count = int(1 / settings.DECIDE_BILLING_SAMPLING_RATE)
                    increment_request_count(team.pk, count)

            # Analytics for decide requests with feature flags
            # Only send once flag definitions are loaded
            # don't block on loading flag definitions
            if posthoganalytics.feature_flag_definitions() and posthoganalytics.feature_enabled(
                "decide-analytics", distinct_id, only_evaluate_locally=True, send_feature_flag_events=False
            ):
                posthoganalytics.capture(
                    team.id,
                    "decide request",
                    {
                        "team_id": team.id,
                        "flags": len(feature_flags),
                        "captured_distinct_id": distinct_id,
                    },
                    groups={
                        "project": str(team.uuid),
                    },
                )
        else:
            # no auth provided
            return cors_response(
                request,
                generate_exception_response(
                    "decide",
                    "No project API key provided. You can find your project API key in PostHog project settings.",
                    code="no_api_key",
                    type="authentication_error",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )

    statsd.incr(f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "decide"})
    return cors_response(request, JsonResponse(response))
