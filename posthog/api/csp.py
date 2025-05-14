import json
import structlog

from posthog.exceptions import generate_exception_response
from posthog.utils_cors import cors_response
from posthog.models.utils import uuid7

logger = structlog.get_logger(__name__)


# https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/report-uri
def parse_report_uri(data: dict) -> dict:
    report_uri_data = data["csp-report"]
    current_url = report_uri_data.get("document-uri")
    properties = {"$current_url": current_url, **report_uri_data}
    return properties


# https://developer.mozilla.org/en-US/docs/Web/API/CSPViolationReportBody#obtaining_a_cspviolationreportbody_object
def parse_report_to(data: dict) -> dict:
    report_to_data = data.get("body", {})
    current_url = report_to_data.get("documentURL") or report_to_data.get("document-uri") or data.get("url")
    properties = {"$current_url": current_url, **report_to_data}
    return properties


def parse_properties(data: dict) -> dict:
    if "csp-report" in data:
        return parse_report_uri(data)
    elif "type" in data and data["type"] == "csp-violation":
        return parse_report_to(data)
    else:
        raise ValueError("Invalid CSP report")


def process_csp_report(request):
    """
    Process a Content Security Policy (CSP) report from a browser.

    Takes the incoming CSP report JSON, formats it as a PostHog event,
    and returns it for ingestion through the regular event pipeline.

    Returns:
        tuple: (csp_report, error_response)
            - csp_report: The formatted CSP report as a PostHog event, or None if processing failed
            - error_response: An error response to return to the client if processing failed, or None if successful
    """
    # Early return if the request is not a CSP report and keep the ingestion pipeline working as it was
    if request.content_type != "application/csp-report" and request.content_type != "application/reports+json":
        return None, None

    try:
        csp_data = json.loads(request.body)
        # Try to get distinct_id from query params or generate a new one
        distinct_id = request.GET.get("distinct_id") or request.GET.get("id") or str(uuid7())

        try:
            properties = parse_properties(csp_data)

            return {
                "event": "$csp_violation",
                "distinct_id": distinct_id,
                "properties": properties,
            }, None
        except ValueError as e:
            logger.exception("Invalid CSP report parsing", error=e)
            return None, None

    except json.JSONDecodeError:
        return None, cors_response(
            request,
            generate_exception_response("capture", "Invalid CSP report format", code="invalid_payload"),
        )
