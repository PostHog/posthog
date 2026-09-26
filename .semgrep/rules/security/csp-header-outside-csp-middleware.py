# Test cases for csp-header-outside-csp-middleware rule
# ruff: noqa: F821, F841, E501 — assignments exist solely to give semgrep something to match

from django.http import HttpResponse


def flag_subscript_assignment(response):
    # ruleid: csp-header-outside-csp-middleware
    response["Content-Security-Policy"] = "default-src 'none'"


def flag_headers_assignment(response):
    # ruleid: csp-header-outside-csp-middleware
    response.headers["Content-Security-Policy"] = "default-src 'self'"


def flag_report_only_header(response):
    # ruleid: csp-header-outside-csp-middleware
    response.headers["Content-Security-Policy-Report-Only"] = "default-src 'self'"


def flag_lowercase_header(response):
    # ruleid: csp-header-outside-csp-middleware
    response["content-security-policy"] = "default-src 'none'"


def flag_setdefault(response):
    # ruleid: csp-header-outside-csp-middleware
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'")


def flag_headers_update(response):
    # ruleid: csp-header-outside-csp-middleware
    response.headers.update({"X-Frame-Options": "DENY", "Content-Security-Policy": "sandbox"})


def flag_response_constructor():
    # ruleid: csp-header-outside-csp-middleware
    return HttpResponse("<p>hi</p>", headers={"Content-Security-Policy": "sandbox"})


def ok_canvas_artifact_policy(response, network_origins):
    # ok: csp-header-outside-csp-middleware
    response["Content-Security-Policy"] = artifact_csp(network_origins)


def ok_public_survey_policy(request, response):
    # ok: csp-header-outside-csp-middleware
    response["Content-Security-Policy"] = _public_survey_csp(request)


def ok_workflow_asset_policy(response):
    # ok: csp-header-outside-csp-middleware
    response["Content-Security-Policy"] = (
        "sandbox; default-src 'none'; img-src https: data:; style-src 'unsafe-inline'"
    )


def flag_report_only_canvas_artifact_policy(response, network_origins):
    # ruleid: csp-header-outside-csp-middleware
    response["Content-Security-Policy-Report-Only"] = artifact_csp(network_origins)


def flag_report_only_public_survey_policy(request, response):
    # ruleid: csp-header-outside-csp-middleware
    response["Content-Security-Policy-Report-Only"] = _public_survey_csp(request)


def flag_report_only_workflow_asset_policy(response):
    # ruleid: csp-header-outside-csp-middleware
    response["Content-Security-Policy-Report-Only"] = (
        "sandbox; default-src 'none'; img-src https: data:; style-src 'unsafe-inline'"
    )


def flag_changed_workflow_asset_policy(response):
    # ruleid: csp-header-outside-csp-middleware
    response["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src https: data:; script-src 'self'"


def flag_second_policy_in_an_excepted_file(response):
    # ruleid: csp-header-outside-csp-middleware
    response["Content-Security-Policy"] = "default-src 'none'; frame-ancestors *"


def ok_other_security_header(response):
    # ok: csp-header-outside-csp-middleware
    response["X-Content-Type-Options"] = "nosniff"


def ok_reads_the_header(response):
    # ok: csp-header-outside-csp-middleware
    return "Content-Security-Policy" in response.headers


def ok_reporting_endpoints_header(response):
    # ok: csp-header-outside-csp-middleware
    response.headers["Reporting-Endpoints"] = 'posthog="https://example.com/report/"'
