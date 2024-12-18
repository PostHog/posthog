from random import random
from typing import Any, Union

import structlog
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from prometheus_client import Counter
from rest_framework import status
from sentry_sdk import capture_exception
from statshog.defaults.django import statsd

from posthog.api.survey import SURVEY_TARGETING_FLAG_PREFIX
from posthog.api.utils import (
    get_project_id,
    get_token,
    on_permitted_recording_domain,
)
from posthog.database_healthcheck import DATABASE_FOR_FLAG_MATCHING
from posthog.exceptions import (
    RequestParsingError,
    UnspecifiedCompressionFallbackParsingError,
    generate_exception_response,
)
from posthog.geoip import get_geoip_properties
from posthog.logging.timing import timed
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Team, User
from posthog.models.feature_flag import get_all_feature_flags
from posthog.models.feature_flag.flag_analytics import increment_request_count
from posthog.models.filters.mixins.utils import process_bool
from posthog.models.remote_config import RemoteConfig
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

REMOTE_CONFIG_CACHE_COUNTER = Counter(
    "posthog_remote_config_for_decide",
    "Metric tracking whether Remote Config was used for decide",
    labelnames=["result"],
)


def get_base_config(token: str, team: Team, request: HttpRequest, skip_db: bool = False) -> dict:
    use_remote_config = False

    # Explicitly set via query param for testing otherwise rollout percentage
    if request.GET.get("use_remote_config") == "true":
        use_remote_config = True
    elif request.GET.get("use_remote_config") == "false":
        use_remote_config = False
    elif settings.REMOTE_CONFIG_DECIDE_ROLLOUT_PERCENTAGE > 0:
        if random() < settings.REMOTE_CONFIG_DECIDE_ROLLOUT_PERCENTAGE:
            use_remote_config = True

    REMOTE_CONFIG_CACHE_COUNTER.labels(result=use_remote_config).inc()

    if use_remote_config:
        response = RemoteConfig.get_config_via_token(token, request=request)

        # Add in a bunch of backwards compatibility stuff
        response["isAuthenticated"] = False
        response["toolbarParams"] = {}
        response["config"] = {"enable_collect_everything": True}
        response["surveys"] = True if len(response["surveys"]) > 0 else False

        # Remove some stuff that is specific to the new RemoteConfig
        del response["hasFeatureFlags"]
        del response["token"]

        return response

    response = {
        "config": {"enable_collect_everything": True},
        "toolbarParams": {},
        "isAuthenticated": False,
        # gzip and gzip-js are aliases for the same compression algorithm
        "supportedCompression": ["gzip", "gzip-js"],
        "featureFlags": [],
        "sessionRecording": False,
    }

    response["captureDeadClicks"] = True if team.capture_dead_clicks else False

    capture_network_timing = True if team.capture_performance_opt_in else False
    capture_web_vitals = True if team.autocapture_web_vitals_opt_in else False
    autocapture_web_vitals_allowed_metrics = None
    if capture_web_vitals:
        autocapture_web_vitals_allowed_metrics = team.autocapture_web_vitals_allowed_metrics
    response["capturePerformance"] = (
        {
            "network_timing": capture_network_timing,
            "web_vitals": capture_web_vitals,
            "web_vitals_allowed_metrics": autocapture_web_vitals_allowed_metrics,
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

    # this not settings.DEBUG check is a lazy workaround because
    # NEW_ANALYTICS_CAPTURE_ENDPOINT doesn't currently work in DEBUG mode
    if not settings.DEBUG and str(team.id) not in (settings.NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS or []):
        response["analytics"] = {"endpoint": settings.NEW_ANALYTICS_CAPTURE_ENDPOINT}

    if str(team.id) not in (settings.ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS or []):
        response["elementsChainAsString"] = True

    response["sessionRecording"] = _session_recording_config_response(request, team)

    if settings.DECIDE_SESSION_REPLAY_QUOTA_CHECK:
        from ee.billing.quota_limiting import (
            QuotaLimitingCaches,
            QuotaResource,
            list_limited_team_attributes,
        )

        limited_tokens_recordings = list_limited_team_attributes(
            QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )

        if token in limited_tokens_recordings:
            response["quotaLimited"] = ["recordings"]
            response["sessionRecording"] = False

    response["surveys"] = True if team.surveys_opt_in else False
    response["heatmaps"] = True if team.heatmaps_opt_in else False
    response["defaultIdentifiedOnly"] = True  # Support old SDK versions with setting that is now the default

    site_apps = []
    # errors mean the database is unavailable, bail in this case
    if team.inject_web_apps and not skip_db:
        try:
            with execute_with_timeout(200, DATABASE_FOR_FLAG_MATCHING):
                site_apps = get_decide_site_apps(team, using_database=DATABASE_FOR_FLAG_MATCHING)
        except Exception:
            pass

    response["siteApps"] = site_apps

    return response


@csrf_exempt
@timed("posthog_cloud_decide_endpoint")
def get_decide(request: HttpRequest):
    # handle cors request
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": 1}))

    if request.method != "POST":
        statsd.incr(f"posthog_cloud_raw_endpoint_success", tags={"endpoint": "decide"})
        return cors_response(
            request,
            JsonResponse(
                {
                    "config": {"enable_collect_everything": True},
                    "toolbarParams": {},
                    "isAuthenticated": False,
                    # gzip and gzip-js are aliases for the same compression algorithm
                    "supportedCompression": ["gzip", "gzip-js"],
                    "featureFlags": [],
                    "sessionRecording": False,
                }
            ),
        )

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
        if team.id in settings.DECIDE_SHORT_CIRCUITED_TEAM_IDS:
            return cors_response(
                request,
                generate_exception_response(
                    "decide",
                    f"Team with ID {team.id} cannot access the /decide endpoint."
                    f"Please contact us at hey@posthog.com",
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                ),
            )

        token = team.api_token

        structlog.contextvars.bind_contextvars(team_id=team.id)

        disable_flags = process_bool(data.get("disable_flags")) is True
        feature_flags = None
        errors = False
        flags_response: dict[str, Any] = {}

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
                flags_response["featureFlags"] = active_flags
            elif api_version >= 3:
                # v3 returns all flags, not just active ones, as well as if there was an error computing all flags
                flags_response["featureFlags"] = feature_flags
                flags_response["errorsWhileComputingFlags"] = errors
                flags_response["featureFlagPayloads"] = feature_flag_payloads
            else:
                # default v1
                flags_response["featureFlags"] = list(active_flags.keys())

            # metrics for feature flags
            team_id_label = label_for_team_id_to_track(team.pk)
            FLAG_EVALUATION_COUNTER.labels(
                team_id=team_id_label,
                errors_computing=errors,
                has_hash_key_override=bool(data.get("$anon_distinct_id")),
            ).inc()
        else:
            flags_response["featureFlags"] = {}

        # NOTE: Changed code - everything not feature flags goes in here
        response = get_base_config(token, team, request, skip_db=errors)
        response.update(flags_response)

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


def _session_recording_domain_not_allowed(team: Team, request: HttpRequest) -> bool:
    return team.recording_domains and not on_permitted_recording_domain(team.recording_domains, request)


def _session_recording_config_response(request: HttpRequest, team: Team) -> bool | dict:
    session_recording_config_response: bool | dict = False

    try:
        if team.session_recording_opt_in and not _session_recording_domain_not_allowed(team, request):
            capture_console_logs = True if team.capture_console_log_opt_in else False
            sample_rate = str(team.session_recording_sample_rate) if team.session_recording_sample_rate else None
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

            rrweb_script_config = None

            if (settings.SESSION_REPLAY_RRWEB_SCRIPT is not None) and (
                "*" in settings.SESSION_REPLAY_RRWEB_SCRIPT_ALLOWED_TEAMS
                or str(team.id) in settings.SESSION_REPLAY_RRWEB_SCRIPT_ALLOWED_TEAMS
            ):
                rrweb_script_config = {
                    "script": settings.SESSION_REPLAY_RRWEB_SCRIPT,
                }

            session_recording_config_response = {
                "endpoint": "/s/",
                "consoleLogRecordingEnabled": capture_console_logs,
                "recorderVersion": "v2",
                "sampleRate": sample_rate,
                "minimumDurationMilliseconds": minimum_duration,
                "linkedFlag": linked_flag,
                "networkPayloadCapture": team.session_recording_network_payload_capture_config or None,
                "urlTriggers": team.session_recording_url_trigger_config,
                "urlBlocklist": team.session_recording_url_blocklist_config,
                "eventTriggers": team.session_recording_event_trigger_config,
                "scriptConfig": rrweb_script_config,
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
