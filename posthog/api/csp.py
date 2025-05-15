import json
import structlog

from posthog.exceptions import generate_exception_response
from posthog.utils_cors import cors_response
from posthog.models.utils import uuid7

logger = structlog.get_logger(__name__)

"""
| Normalized Key        | report-to format                     | report-uri format                  |
| --------------------- | ------------------------------------ | ---------------------------------- |
| `document_url`        | `body.documentURL`                   | `csp-report.document-uri`          |
| `referrer`            | `body.referrer`                      | `csp-report.referrer`              |
| `violated_directive`  | *inferred from* `effectiveDirective` | `csp-report.violated-directive`    |
| `effective_directive` | `body.effectiveDirective`            | `csp-report.effective-directive`   |
| `original_policy`     | `body.originalPolicy`                | `csp-report.original-policy`       |
| `disposition`         | `body.disposition`                   | `csp-report.disposition`           |
| `blocked_url`         | `body.blockedURL`                    | `csp-report.blocked-uri`           |
| `line_number`         | `body.lineNumber`                    | `csp-report.line-number`           |
| `column_number`       | `body.columnNumber`                  | *not available*                    |
| `source_file`         | `body.sourceFile`                    | `csp-report.source-file`           |
| `status_code`         | `body.statusCode`                    | `csp-report.status-code`           |
| `script_sample`       | `body.sample`                        | `csp-report.script-sample`         |
| `user_agent`          | top-level `user_agent`               | *custom extract from headers*      |
| `report_type`         | top-level `type`                     | `"csp-violation"` (static/assumed) |
"""


# https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/report-uri
def parse_report_uri(data: dict) -> dict:
    report_uri_data = data["csp-report"]
    # Map report-uri format to normalized keys
    properties = {
        "report_type": "csp-violation",
        "$current_url": report_uri_data.get("document-uri"),
        "document_url": report_uri_data.get("document-uri"),
        "referrer": report_uri_data.get("referrer"),
        "violated_directive": report_uri_data.get("violated-directive"),
        "effective_directive": report_uri_data.get("effective-directive"),
        "original_policy": report_uri_data.get("original-policy"),
        "disposition": report_uri_data.get("disposition"),
        "blocked_url": report_uri_data.get("blocked-uri"),
        "line_number": report_uri_data.get("line-number"),
        "source_file": report_uri_data.get("source-file"),
        "status_code": report_uri_data.get("status-code"),
        "script_sample": report_uri_data.get("script-sample"),
        "raw_report": data,  # While we're testing, keep the raw report for debugging
    }
    return properties


# https://developer.mozilla.org/en-US/docs/Web/API/CSPViolationReportBody#obtaining_a_cspviolationreportbody_object
def parse_report_to(data: dict) -> dict:
    report_to_data = data.get("body", {})
    user_agent = data.get("user_agent") or report_to_data.get("user-agent")
    report_type = data.get("type")

    # Map report-to format to normalized keys
    properties = {
        "report_type": report_type,
        "$current_url": report_to_data.get("documentURL") or report_to_data.get("document-uri") or data.get("url"),
        "document_url": report_to_data.get("documentURL") or report_to_data.get("document-uri"),
        "referrer": report_to_data.get("referrer"),
        "violated_directive": report_to_data.get("effectiveDirective")
        or report_to_data.get("violated-directive"),  # Inferring from effectiveDirective
        "effective_directive": report_to_data.get("effectiveDirective"),
        "original_policy": report_to_data.get("originalPolicy"),
        "disposition": report_to_data.get("disposition"),
        "blocked_url": report_to_data.get("blockedURL") or report_to_data.get("blocked-uri"),
        "line_number": report_to_data.get("lineNumber"),
        "column_number": report_to_data.get("columnNumber"),
        "source_file": report_to_data.get("sourceFile"),
        "status_code": report_to_data.get("statusCode"),
        "script_sample": report_to_data.get("sample"),
        "user_agent": user_agent,
        "raw_report": data,  # Keep the raw report for debugging
    }
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
    try:
        # If by any chance we got this far and this is not looking like a CSP report, keep the ingestion pipeline working as it was
        # we don't want to return an error here to avoid breaking the ingestion pipeline
        if request.content_type != "application/csp-report" and request.content_type != "application/reports+json":
            return None, None

        csp_data = json.loads(request.body)

        distinct_id = request.GET.get("distinct_id") or request.GET.get("id") or str(uuid7())
        session_id = request.GET.get("session_id") or request.GET.get("id") or str(uuid7())
        version = request.GET.get("v") or "unknown"

        properties = parse_properties(csp_data)

        return {
            "event": "$csp_violation",
            "distinct_id": distinct_id,
            "properties": {"$session_id": session_id, "csp_version": version, **properties},
        }, None

    except json.JSONDecodeError:
        return None, cors_response(
            request,
            generate_exception_response("capture", "Invalid CSP report format", code="invalid_csp_payload"),
        )
    except ValueError as e:
        logger.exception("Invalid CSP report properties are being parsed", error=e)
        return None, cors_response(
            request,
            generate_exception_response(
                "capture", "Invalid CSP report properties provided", code="invalid_csp_payload"
            ),
        )
    except Exception as e:
        logger.exception("Error processing CSP report", error=e)
        return None, None
