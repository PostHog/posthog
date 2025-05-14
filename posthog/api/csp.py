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

    user_agent = report_to_data.get("user-agent") or data.get("user_agent")
    current_url = report_to_data.get("documentURL") or report_to_data.get("document-uri") or data.get("url")

    properties = {
        "$current_url": current_url,
        "$user_agent": user_agent,
        "$report_to": data.get("report-to"),
    }

    field_mapping = {
        "blockedURL": "blocked-uri",
        "sourceFile": "source-file",
        "originalPolicy": "original-policy",
    }

    # Add body fields with appropriate mapping
    for key, value in report_to_data.items():
        if key in ["sample", "script-sample", "sourceCodeExample"]:
            # Redact all script samples for security
            properties[key] = "REDACTED"
        elif key in field_mapping:
            # Map certain fields to kebab-case for consistency
            properties[field_mapping[key]] = value
        else:
            properties[key] = value

    # Check for blockedURL at the top level if not in body
    if "blockedURL" in data and "blocked-uri" not in properties:
        properties["blocked-uri"] = data["blockedURL"]
    elif "blockedURI" in report_to_data and "blocked-uri" not in properties:
        properties["blocked-uri"] = report_to_data["blockedURI"]

    # Add remaining top-level fields (except body and type)
    for key, value in data.items():
        if key not in ["body", "type"] and key not in properties:
            properties[key] = value

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
        session_id = request.GET.get("session_id") or str(uuid7())
        version = request.GET.get("v") or "unknown"

        # Parse the properties from the CSP report
        properties = parse_properties(csp_data)

        return {
            "event": "$csp_violation",
            "distinct_id": distinct_id,
            "session_id": session_id,
            "version": version,
            "properties": properties,
        }, None

    except json.JSONDecodeError:
        return None, cors_response(
            request,
            generate_exception_response("capture", "Invalid CSP report format", code="invalid_payload"),
        )
