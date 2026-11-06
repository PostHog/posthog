import json
from typing import Literal
from urllib.parse import unquote

from django.conf import settings
from django.http import HttpRequest

import posthoganalytics
from prometheus_client import Counter

from posthog.cloud_utils import is_cloud
from posthog.constants import POSTHOG_JS_CLOUD_TOKEN
from posthog.exceptions_capture import capture_exception

LOGIN_ENTRY_FLAG = "standalone-login-entry"

LOGIN_ENTRY_ASSIGNMENT_COUNTER = Counter(
    "posthog_login_entry_assignment_total",
    "Eligible login page requests, by login entry experiment outcome.",
    labelnames=["outcome"],
)

AssignmentOutcome = Literal["control", "test", "no_identity", "not_enrolled", "flag_unavailable", "error"]


class LoginEntryExperiment:
    @staticmethod
    def variant(request: HttpRequest) -> Literal["control", "test"] | None:
        if (
            request.method != "GET"
            or request.path.rstrip("/") != "/login"
            or request.user.is_authenticated
            or request.GET.get("auth_app") is not None
            or not is_cloud()
            or request.get_host() != "us.posthog.com"
            or settings.OPT_OUT_CAPTURE
        ):
            return None

        outcome = LoginEntryExperiment._assign(request)
        LOGIN_ENTRY_ASSIGNMENT_COUNTER.labels(outcome=outcome).inc()
        if outcome == "control" or outcome == "test":
            return outcome
        return None

    @staticmethod
    def _assign(request: HttpRequest) -> AssignmentOutcome:
        try:
            identity = json.loads(unquote(request.COOKIES.get(f"ph_{POSTHOG_JS_CLOUD_TOKEN}_posthog", "null")))
        except (ValueError, UnicodeError):
            return "no_identity"
        if not isinstance(identity, dict):
            return "no_identity"
        distinct_id, device_id = identity.get("distinct_id"), identity.get("$device_id")
        if not isinstance(distinct_id, str) or not isinstance(device_id, str):
            return "no_identity"
        if not 0 < len(distinct_id) <= 200 or not 0 < len(device_id) <= 200:
            return "no_identity"

        try:
            with posthoganalytics.new_context():
                posthoganalytics.set_context_device_id(device_id)
                variant = posthoganalytics.get_feature_flag(
                    LOGIN_ENTRY_FLAG,
                    distinct_id,
                    device_id=device_id,
                    only_evaluate_locally=True,
                    send_feature_flag_events=False,
                )
                if variant is False:
                    return "not_enrolled"
                if variant not in ("control", "test"):
                    return "flag_unavailable"
                posthoganalytics.capture(
                    distinct_id=distinct_id,
                    event="$feature_flag_called",
                    properties={
                        "$feature_flag": LOGIN_ENTRY_FLAG,
                        "$feature_flag_response": variant,
                        "$device_id": device_id,
                        "login_entry_exposure": True,
                        f"$feature/{LOGIN_ENTRY_FLAG}": variant,
                        "$current_url": request.build_absolute_uri(request.path),
                    },
                )
        except Exception as error:
            capture_exception(error)
            return "error"
        return "test" if variant == "test" else "control"
