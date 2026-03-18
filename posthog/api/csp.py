import json
from datetime import UTC, datetime
from typing import Optional

from django.http import HttpResponse
from django.utils.html import escape

import structlog
from rest_framework import status

from posthog.exceptions import generate_exception_response
from posthog.models.utils import uuid7
from posthog.sampling import sample_on_property
from posthog.utils_cors import cors_response

logger = structlog.get_logger(__name__)

CSP_REPORT_TYPES_MAPPING_TABLE = """
| Normalized Key             | report-to format                     | report-uri format                  |
| -------------------------- | ------------------------------------ | ---------------------------------- |
| `$csp_document_url`        | `body.documentURL`                   | `csp-report.document-uri`          |
| `$csp_referrer`            | `body.referrer`                      | `csp-report.referrer`              |
| `$csp_violated_directive`  | same as `effectiveDirective`         | `csp-report.violated-directive`    |
| `$csp_effective_directive` | `body.effectiveDirective`            | `csp-report.effective-directive`   |
| `$csp_original_policy`     | `body.originalPolicy`                | `csp-report.original-policy`       |
| `$csp_disposition`         | `body.disposition`                   | `csp-report.disposition`           |
| `$csp_blocked_url`         | `body.blockedURL`                    | `csp-report.blocked-uri`           |
| `$csp_line_number`         | `body.lineNumber`                    | `csp-report.line-number`           |
| `$csp_column_number`       | `body.columnNumber`                  | `csp-report.column-number`         |
| `$csp_source_file`         | `body.sourceFile`                    | `csp-report.source-file`           |
| `$csp_status_code`         | `body.statusCode`                    | `csp-report.status-code`           |
| `$csp_script_sample`       | `body.sample`                        | `csp-report.script-sample`         |
| `$csp_user_agent`          | top-level `user_agent`               | not available                      |
| `$csp_report_type`         | top-level `type`                     | `"csp-violation"` constant         |
"""


def sample_csp_report(properties: dict, percent: float, add_metadata: bool = False) -> bool:
    if percent >= 1.0:
        return True

    document_url = properties.get("document_url", "")
    now = datetime.now().replace(second=0, microsecond=0)
    time_str = now.isoformat()
    sampling_key = f"{document_url}-{time_str}"

    should_ingest_report = sample_on_property(sampling_key, percent)

    if add_metadata:
        properties["csp_sampled"] = should_ingest_report
        properties["csp_sample_threshold"] = percent
        properties["csp_sampling_key"] = sampling_key

    if not should_ingest_report:
        logger.debug(
            "CSP report sampled out",
            document_url=document_url,
            sampling_key=sampling_key,
            sample_rate=percent,
        )

    return should_ingest_report


# https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/report-uri
def parse_report_uri(data: dict) -> dict:
    report_uri_data = data["csp-report"]

    report_uri_data["script-sample"] = escape(report_uri_data.get("script-sample") or "")

    # Map report-uri format to normalized keys
    properties = {
        "report_type": "csp-violation",
        "document_url": report_uri_data.get("document-uri"),
        "referrer": report_uri_data.get("referrer"),
        "violated_directive": report_uri_data.get("violated-directive"),
        "effective_directive": report_uri_data.get("effective-directive"),
        "original_policy": report_uri_data.get("original-policy"),
        "disposition": report_uri_data.get("disposition"),
        "blocked_url": report_uri_data.get("blocked-uri"),
        "line_number": report_uri_data.get("line-number"),
        "column_number": report_uri_data.get("column-number"),
        "source_file": report_uri_data.get("source-file"),
        "status_code": report_uri_data.get("status-code"),
        "script_sample": report_uri_data.get("script-sample"),
        # Keep the raw report for debugging
        "raw_report": data,
    }
    return properties


# https://developer.mozilla.org/en-US/docs/Web/API/CSPViolationReportBody
def parse_report_to(data: dict) -> dict:
    report_to_data = data.get("body", {})
    user_agent = data.get("user_agent") or report_to_data.get("user-agent")

    report_to_data["sample"] = escape(report_to_data.get("sample") or "")
    report_to_data["script-sample"] = escape(report_to_data.get("sample") or "")
    properties = {
        "report_type": data.get("type"),
        "document_url": report_to_data.get("documentURL") or report_to_data.get("document-uri") or data.get("url"),
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
        # Keep the raw report for debugging
        "raw_report": data,
    }
    return properties


def is_csp_violation(data: dict) -> bool:
    return "type" in data and data["type"] == "csp-violation"


def build_csp_event(props: dict, distinct_id: str, session_id: str, version: str, user_agent: Optional[str]) -> dict:
    props = {f"$csp_{k}": v for k, v in props.items()}

    return {
        "event": "$csp_violation",
        "distinct_id": distinct_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "properties": {
            "$session_id": session_id,
            "$csp_version": version,
            "$current_url": props["$csp_document_url"],
            "$process_person_profile": False,
            "$raw_user_agent": user_agent,
            **props,
        },
    }


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
            logger.warning(
                "CSP report skipped - invalid content type",
                content_type=request.content_type,
                expected_types=["application/csp-report", "application/reports+json"],
            )
            return None, None

        csp_data = json.loads(request.body)

        distinct_id = request.GET.get("distinct_id") or str(uuid7())
        session_id = request.GET.get("session_id") or str(uuid7())
        version = request.GET.get("v") or "unknown"
        user_agent = request.headers.get("User-Agent")

        try:
            sample_rate = request.GET.get("sample_rate", 1.0)
            sample_rate = float(sample_rate)
        except (ValueError, TypeError):
            sample_rate = 1.0

        if request.content_type == "application/csp-report":
            if "csp-report" in csp_data:
                properties = parse_report_uri(csp_data)
            elif is_csp_violation(csp_data):
                properties = parse_report_to(csp_data)
            else:
                raise ValueError("Invalid CSP report")

            if not sample_csp_report(properties, sample_rate, add_metadata=True):
                logger.warning(
                    "CSP report sampled out - report-uri format",
                    document_url=properties.get("document_url"),
                    sample_rate=sample_rate,
                )
                return None, cors_response(request, HttpResponse(status=status.HTTP_204_NO_CONTENT))

            return (
                build_csp_event(
                    properties,
                    distinct_id,
                    session_id,
                    version,
                    user_agent,
                ),
                None,
            )

        if request.content_type == "application/reports+json":
            if isinstance(csp_data, list):
                violations_props = [parse_report_to(item) for item in csp_data if is_csp_violation(item)]
            elif isinstance(csp_data, dict) and is_csp_violation(csp_data):
                violations_props = [parse_report_to(csp_data)]
            else:
                raise ValueError("Invalid CSP report")

            sampled_violations = []
            for prop in violations_props:
                if sample_csp_report(prop, sample_rate, add_metadata=True):
                    sampled_violations.append(prop)

            if not sampled_violations:
                logger.warning(
                    "CSP report sampled out - report-to format",
                    total_violations=len(violations_props),
                    sample_rate=sample_rate,
                )
                return None, cors_response(request, HttpResponse(status=status.HTTP_204_NO_CONTENT))

            return [
                build_csp_event(prop, distinct_id, session_id, version, user_agent) for prop in sampled_violations
            ], None

        else:
            raise ValueError("Invalid CSP report")

    except json.JSONDecodeError as e:
        logger.exception("Invalid CSP report JSON format", error=e)
        return None, cors_response(
            request,
            generate_exception_response("capture", "Invalid CSP report format", code="invalid_csp_payload"),
        )
    except ValueError as e:
        logger.exception("Invalid CSP report properties", error=e)
        return None, cors_response(
            request,
            generate_exception_response(
                "capture", "Invalid CSP report properties provided", code="invalid_csp_payload"
            ),
        )
    except Exception as e:
        logger.exception("CSP report processing failed with exception", error=e)
        return None, None
