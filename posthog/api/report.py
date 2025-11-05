from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from requests import HTTPError
from rest_framework import status

from posthog.api.capture import capture_batch_internal, capture_internal
from posthog.api.csp import process_csp_report
from posthog.api.utils import get_token
from posthog.exceptions import generate_exception_response
from posthog.exceptions_capture import capture_exception
from posthog.logging.timing import timed
from posthog.utils_cors import cors_response

logger = structlog.get_logger(__name__)


@csrf_exempt
@timed("posthog_cloud_csp_event_endpoint")
def get_csp_event(request):
    # we want to handle this as early as possible and avoid any processing
    if request.method == "OPTIONS":
        return cors_response(request, JsonResponse({"status": 1}))

    debug_enabled = request.GET.get("debug", "").lower() == "true"
    if debug_enabled:
        logger.exception(
            "CSP debug request",
            error=ValueError("CSP debug request"),
            method=request.method,
            url=request.build_absolute_uri(),
            content_type=request.content_type,
            headers=dict(request.headers),
            query_params=dict(request.GET),
            body_size=len(request.body) if request.body else 0,
            body=request.body.decode("utf-8", errors="ignore") if request.body else None,
        )

    csp_report, error_response = process_csp_report(request)
    if error_response:
        return error_response

    # mimic what get_event does if no data is returned from process_csp_report
    if not csp_report:
        return cors_response(
            request,
            generate_exception_response(
                "csp_report_capture",
                f"Failed to submit CSP report",
                code="invalid_payload",
                type="invalid_payload",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )

    try:
        token = get_token(csp_report, request)
        if not token:
            token = ""

        if isinstance(csp_report, list):
            futures = capture_batch_internal(
                events=csp_report, event_source="get_csp_report", token=token, process_person_profile=False
            )
            for future in futures:
                result = future.result()
                result.raise_for_status()
        else:
            resp = capture_internal(
                token=token,
                event_name=csp_report.get("event", ""),
                event_source="get_csp_report",
                distinct_id=csp_report.get("distinct_id", ""),
                timestamp=csp_report.get("timestamp", None),
                properties=csp_report.get("properties", {}),
                process_person_profile=False,
            )
            resp.raise_for_status()

        return cors_response(request, HttpResponse(status=status.HTTP_204_NO_CONTENT))

    except HTTPError as hte:
        capture_exception(hte, {"capture-http": "csp_report", "ph-team-token": token})
        logger.exception("csp_report_capture_http_error", exc_info=hte)
        return cors_response(
            request,
            generate_exception_response(
                "csp_report_capture",
                f"Failed to submit CSP report",
                code="capture_http_error",
                type="capture_http_error",
                status_code=hte.response.status_code,
            ),
        )
    except Exception as e:
        capture_exception(e, {"capture-pathway": "csp_report", "ph-team-token": token})
        logger.exception("csp_report_capture_error", exc_info=e)
        return cors_response(
            request,
            generate_exception_response(
                "csp_report_capture",
                f"Failed to submit CSP report",
                code="capture_error",
                type="capture_error",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
        )
