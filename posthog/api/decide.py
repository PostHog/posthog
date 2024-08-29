from random import random
from typing import Union, cast

import structlog
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from prometheus_client import Counter
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.api.geoip import get_geoip_properties
from posthog.api.survey import SURVEY_TARGETING_FLAG_PREFIX
from posthog.api.utils import get_project_id, get_token, hostname_in_allowed_url_list, parse_domain
from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.exceptions import (
    UnspecifiedCompressionFallbackParsingError,
    RequestParsingError,
    generate_exception_response,
)
from posthog.logging.timing import timed
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Team, User
from posthog.models.feature_flag import get_all_feature_flags
from posthog.models.feature_flag.flag_analytics import increment_request_count
from posthog.models.filters.mixins.utils import process_bool
from posthog.models.utils import execute_with_timeout
from posthog.plugins.site import get_decide_site_apps
from posthog.utils import (
    get_ip_address,
    label_for_team_id_to_track,
    load_data_from_request,
)
from posthog.utils_cors import cors_response

FLAG_EVALUATION_COUNTER = Counter(
    "flag_evaluation_total",
    "Successful decide requests per team.",
    labelnames=[LABEL_TEAM_ID, "errors_computing", "has_hash_key_override"],
)


def on_permitted_recording_domain(team: Team, request: HttpRequest) -> bool:
    origin = parse_domain(request.headers.get("Origin"))
    referer = parse_domain(request.headers.get("Referer"))
    user_agent = request.headers.get("user-agent")

    is_authorized_web_client: bool = hostname_in_allowed_url_list(
        team.recording_domains, origin
    ) or hostname_in_allowed_url_list(team.recording_domains, referer)
    # TODO this is a short term fix for beta testers
    # TODO we will match on the app identifier in the origin instead and allow users to auth those
    is_authorized_mobile_client: bool = user_agent is not None and any(
        keyword in user_agent for keyword in ["posthog-android", "posthog-ios"]
    )

    return is_authorized_web_client or is_authorized_mobile_client


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
        "featureFlags": [],
        "sessionRecording": False,
    }

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
        except UnspecifiedCompressionFallbackParsingError as error:
            # Notably don't capture this exception as it's not caused by buggy behavior,
            # it's just a fallback for when we can't parse the request due to a missing header
            # that we attempted to kludge by manually setting the compression type to gzip
            # If this kludge fails, though all we need to do is return a 400 and move on
            return cors_response(
                request,
                generate_exception_response("decide", f"Malformed request data: {error}", code="malformed_data"),
            )
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
            token = cast(str, token)  # we know it's not None if we found a team
            structlog.contextvars.bind_contextvars(team_id=team.id)

            disable_flags = process_bool(data.get("disable_flags")) is True
            feature_flags = None
            errors = False
            if not disable_flags:
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

                all_property_overrides: dict[str, Union[str, int]] = {
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

                # metrics for feature flags
                team_id_label = label_for_team_id_to_track(team.pk)
                FLAG_EVALUATION_COUNTER.labels(
                    team_id=team_id_label,
                    errors_computing=errors,
                    has_hash_key_override=bool(data.get("$anon_distinct_id")),
                ).inc()
            else:
                response["featureFlags"] = {}

            capture_network_timing = True if team.capture_performance_opt_in else False
            capture_web_vitals = True if team.autocapture_web_vitals_opt_in else False
            response["capturePerformance"] = (
                {
                    "network_timing": capture_network_timing,
                    "web_vitals": capture_web_vitals,
                }
                if capture_network_timing or capture_web_vitals
                else False
            )

            response["autocapture_opt_out"] = True if team.autocapture_opt_out else False
            response["autocaptureExceptions"] = (
                {
                    "endpoint": "/e/",
                }
                if team.autocapture_exceptions_opt_in
                else False
            )

            if str(team.id) not in settings.NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS:
                if (
                    "*" in settings.NEW_ANALYTICS_CAPTURE_TEAM_IDS
                    or str(team.id) in settings.NEW_ANALYTICS_CAPTURE_TEAM_IDS
                ):
                    if random() < settings.NEW_ANALYTICS_CAPTURE_SAMPLING_RATE:
                        response["analytics"] = {"endpoint": settings.NEW_ANALYTICS_CAPTURE_ENDPOINT}

            if (
                "*" in settings.NEW_CAPTURE_ENDPOINTS_INCLUDED_TEAM_IDS
                or str(team.id) in settings.NEW_CAPTURE_ENDPOINTS_INCLUDED_TEAM_IDS
            ):
                if random() < settings.NEW_CAPTURE_ENDPOINTS_SAMPLING_RATE:
                    response["__preview_ingestion_endpoints"] = True

            if (
                settings.ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS
                and str(team.id) not in settings.ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS
            ):
                response["elementsChainAsString"] = True

            response["sessionRecording"] = _session_recording_config_response(request, team, token)

            if settings.DECIDE_SESSION_REPLAY_QUOTA_CHECK:
                from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

                limited_tokens_recordings = list_limited_team_attributes(
                    QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
                )

                if token in limited_tokens_recordings:
                    response["quotaLimited"] = ["recordings"]
                    response["sessionRecording"] = False

            response["surveys"] = True if team.surveys_opt_in else False
            response["heatmaps"] = True if team.heatmaps_opt_in else False

            site_apps = []
            # errors mean the database is unavailable, bail in this case
            if team.inject_web_apps and not errors:
                try:
                    with execute_with_timeout(200, DATABASE_FOR_FLAG_MATCHING):
                        site_apps = get_decide_site_apps(team, using_database=DATABASE_FOR_FLAG_MATCHING)
                except Exception:
                    pass

            response["siteApps"] = site_apps

            # NOTE: Whenever you add something to decide response, update this test:
            # `test_decide_doesnt_error_out_when_database_is_down`
            # which ensures that decide doesn't error out when the database is down

            if feature_flags:
                # Billing analytics for decide requests with feature flags
                # Don't count if all requests are for survey targeting flags only.
                if not all(flag.startswith(SURVEY_TARGETING_FLAG_PREFIX) for flag in feature_flags.keys()):
                    # Sample no. of decide requests with feature flags
                    if settings.DECIDE_BILLING_SAMPLING_RATE and random() < settings.DECIDE_BILLING_SAMPLING_RATE:
                        count = int(1 / settings.DECIDE_BILLING_SAMPLING_RATE)
                        increment_request_count(team.pk, count)

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


def _session_recording_config_response(request: HttpRequest, team: Team, token: str) -> bool | dict:
    session_recording_config_response: bool | dict = False

    try:
        if team.session_recording_opt_in and (
            on_permitted_recording_domain(team, request) or not team.recording_domains
        ):
            capture_console_logs = True if team.capture_console_log_opt_in else False
            sample_rate = team.session_recording_sample_rate or None
            if sample_rate == "1.00":
                sample_rate = None

            minimum_duration = team.session_recording_minimum_duration_milliseconds or None

            linked_flag = None
            linked_flag_config = team.session_recording_linked_flag or None
            if isinstance(linked_flag_config, dict):
                linked_flag_key = linked_flag_config.get("key", None)
                linked_flag_variant = linked_flag_config.get("variant", None)
                if linked_flag_variant is not None:
                    linked_flag = {"flag": linked_flag_key, "variant": linked_flag_variant}
                else:
                    linked_flag = linked_flag_key

            session_recording_config_response = {
                "endpoint": "/s/",
                "consoleLogRecordingEnabled": capture_console_logs,
                "recorderVersion": "v2",
                "sampleRate": sample_rate,
                "minimumDurationMilliseconds": minimum_duration,
                "linkedFlag": linked_flag,
                "networkPayloadCapture": team.session_recording_network_payload_capture_config or None,
            }

            if isinstance(team.session_replay_config, dict):
                record_canvas = team.session_replay_config.get("record_canvas", False)
                session_recording_config_response.update(
                    {
                        "recordCanvas": record_canvas,
                        # hard coded during beta while we decide on sensible values
                        "canvasFps": 3 if record_canvas else None,
                        "canvasQuality": "0.4" if record_canvas else None,
                    }
                )
    except Exception as e:
        capture_exception(e)  # we don't want to fail decide if session recording config fails to load

    return session_recording_config_response
