import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test.client import Client

from parameterized import parameterized
from rest_framework import status
from structlog.testing import capture_logs

from posthog.api.csp import CSP_REPORT_REJECTED

SINGLE_VIOLATION_REPORT_URI = {
    "csp-report": {
        "document-uri": "https://example.com/foo/bar",
        "violated-directive": "default-src self",
    }
}

SINGLE_VIOLATION_REPORT_TO = {
    "type": "csp-violation",
    "body": {
        "documentURL": "https://example.com/foo/bar",
        "effectiveDirective": "script-src",
    },
}

NON_VIOLATION_REPORT = {
    "type": "deprecation",
    "body": {"id": "some-deprecated-api"},
}


class TestCspReport(BaseTest):
    """
    Test CSP /report/ endpoint that accepts CSP violation report requests and publishes events to capture-rs
    """

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        # it is really important to know that /capture is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)

    @parameterized.expand(
        [
            (
                "report_to_over_count_cap",
                "application/reports+json",
                [SINGLE_VIOLATION_REPORT_TO] * 3,
                {"CSP_REPORT_MAX_REPORTS": 2},
                "too_many_reports",
            ),
            (
                "report_to_over_body_cap",
                "application/reports+json",
                [SINGLE_VIOLATION_REPORT_TO] * 3,
                {"CSP_REPORT_MAX_BODY_BYTES": 64},
                "body_too_large",
            ),
            (
                "report_uri_over_body_cap",
                "application/csp-report",
                SINGLE_VIOLATION_REPORT_URI,
                {"CSP_REPORT_MAX_BODY_BYTES": 64},
                "body_too_large",
            ),
            (
                "report_to_over_count_cap_buffered",
                "application/reports+json",
                [SINGLE_VIOLATION_REPORT_TO] * 3,
                {"CSP_REPORT_MAX_REPORTS": 2, "CSP_REPORT_BUFFERED_FORWARD": True},
                "too_many_reports",
            ),
        ]
    )
    def test_oversized_csp_report_is_rejected_before_expansion(
        self, _name, content_type, payload, overrides, expected_reason
    ):
        rejected_before = CSP_REPORT_REJECTED.labels(reason=expected_reason)._value.get()

        with (
            self.settings(**overrides),
            patch("posthog.api.report.capture_batch_internal") as mock_batch_capture,
            patch("posthog.api.report.capture_internal") as mock_capture,
            patch("posthog.api.report.csp_report_buffer") as mock_buffer,
        ):
            mock_batch_capture.return_value = MagicMock(raise_for_status=MagicMock())
            mock_capture.return_value = MagicMock(raise_for_status=MagicMock())

            response = self.client.post(
                f"/report/?token={self.team.api_token}",
                data=json.dumps(payload),
                content_type=content_type,
            )

        assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        mock_batch_capture.assert_not_called()
        mock_capture.assert_not_called()
        mock_buffer.enqueue.assert_not_called()
        assert CSP_REPORT_REJECTED.labels(reason=expected_reason)._value.get() - rejected_before == 1

    @patch("posthog.api.report.capture_batch_internal")
    def test_mixed_report_types_not_rejected_by_violation_count_cap(self, mock_batch_capture):
        # A reports+json bundle can legitimately carry non-CSP report types (deprecation,
        # intervention, ...) alongside csp-violation entries; the count cap must bound the
        # number of violations that become events, not the raw bundle length.
        mock_batch_capture.return_value = MagicMock(raise_for_status=MagicMock())

        bundle = [SINGLE_VIOLATION_REPORT_TO, NON_VIOLATION_REPORT, NON_VIOLATION_REPORT]

        with self.settings(CSP_REPORT_MAX_REPORTS=1):
            response = self.client.post(
                f"/report/?token={self.team.api_token}",
                data=json.dumps(bundle),
                content_type="application/reports+json",
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_batch_capture.assert_called_once()
        assert len(mock_batch_capture.call_args.kwargs["events"]) == 1

    def test_csp_report_never_logs_request_headers(self):
        with capture_logs() as logs, patch("posthog.api.report.capture_internal") as mock_capture:
            mock_capture.return_value = MagicMock(raise_for_status=MagicMock())

            response = self.client.post(
                f"/report/?token={self.team.api_token}&debug=true",
                data=json.dumps(SINGLE_VIOLATION_REPORT_URI),
                content_type="application/csp-report",
                headers={
                    "cookie": "sessionid=sentinel-session-credential",
                    "authorization": "Bearer sentinel-bearer-credential",
                },
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        rendered_logs = json.dumps(logs, default=str)
        assert "sentinel-session-credential" not in rendered_logs
        assert "sentinel-bearer-credential" not in rendered_logs

    @patch("posthog.api.report.capture_internal")
    def test_submit_csp_report_to_new_internal_capture(self, mock_capture) -> None:
        payload = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "referrer": "https://www.google.com/",
                "violated-directive": "default-src self",
                "effective-directive": "img-src",
                "original-policy": "default-src 'self'; img-src 'self' https://img.example.com",
                "disposition": "enforce",
                "blocked-uri": "https://evil.com/malicious-image.png",
                "line-number": 10,
                "source-file": "https://example.com/foo/bar.html",
                "status-code": 0,
                "script-sample": "alert('hello')",
            }
        }
        resp = self.client.post(
            f"/report/?token={self.team.api_token}", data=json.dumps(payload), content_type="application/csp-report"
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert mock_capture.call_count == 1

    @patch("posthog.api.report.capture_batch_internal")
    def test_submit_csp_report_list_to_new_internal_capture(self, mock_batch_capture) -> None:
        mock_batch_capture.return_value = MagicMock(raise_for_status=MagicMock())

        multiple_violations = [
            {
                "type": "csp-violation",
                "document-uri": "https://example.com/page",
                "referrer": "https://example.com/referrer",
                "violated-directive": "script-src 'self'",
                "effective-directive": "script-src",
                "original-policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self'; object-src 'none'; child-src 'self'; frame-ancestors 'none'; form-action 'self'; upgrade-insecure-requests; block-all-mixed-content; report-uri /csp-violation-report-endpoint/",
                "disposition": "report",
                "blocked-uri": "https://malicious-site.com/evil-script.js",
                "line-number": 42,
                "column-number": 15,
                "source-file": "https://example.com/page",
                "status-code": 200,
                "script-sample": "console.log('test1')",
            },
            {
                "type": "csp-violation",
                "document-uri": "https://example.com/page2",
                "referrer": "https://example.com/referrer2",
                "violated-directive": "script-src 'self'",
                "effective-directive": "script-src",
                "original-policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self'; object-src 'none'; child-src 'self'; frame-ancestors 'none'; form-action 'self'; upgrade-insecure-requests; block-all-mixed-content; report-uri /csp-violation-report-endpoint/",
                "disposition": "report",
                "blocked-uri": "https://malicious-site.com/evil-script2.js",
                "line-number": 66,
                "column-number": 20,
                "source-file": "https://example.com/page2",
                "status-code": 200,
                "script-sample": "console.log('test2')",
            },
            {
                "type": "csp-violation",
                "document-uri": "https://example.com/page3",
                "referrer": "https://example.com/referrer3",
                "violated-directive": "script-src 'self'",
                "effective-directive": "script-src",
                "original-policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; media-src 'self'; object-src 'none'; child-src 'self'; frame-ancestors 'none'; form-action 'self'; upgrade-insecure-requests; block-all-mixed-content; report-uri /csp-violation-report-endpoint/",
                "disposition": "report",
                "blocked-uri": "https://malicious-site.com/evil-script3.js",
                "line-number": 66,
                "column-number": 20,
                "source-file": "https://example.com/page3",
                "status-code": 200,
                "script-sample": "console.log('test3')",
            },
        ]
        resp = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(multiple_violations),
            content_type="application/reports+json",
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        mock_batch_capture.assert_called_once()
        assert len(mock_batch_capture.call_args.kwargs["events"]) == 3

    @patch("posthog.api.report.capture_internal")
    def test_capture_csp_violation(self, mock_capture):
        mock_capture.return_value = MagicMock(status_code=204)

        csp_report = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "referrer": "https://www.google.com/",
                "violated-directive": "default-src self",
                "effective-directive": "img-src",
                "original-policy": "default-src 'self'; img-src 'self' https://img.example.com",
                "disposition": "enforce",
                "blocked-uri": "https://evil.com/malicious-image.png",
                "line-number": 10,
                "source-file": "https://example.com/foo/bar.html",
                "status-code": 0,
                "script-sample": "",
            }
        }

        response = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(csp_report),
            content_type="application/csp-report",
        )

        assert status.HTTP_204_NO_CONTENT == response.status_code
        assert mock_capture.call_count == 1

    @patch("posthog.api.report.capture_internal")
    def test_capture_csp_no_trailing_slash(self, mock_capture):
        mock_capture.return_value = MagicMock(status_code=204)

        csp_report = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "referrer": "https://www.google.com/",
                "violated-directive": "default-src self",
                "effective-directive": "img-src",
                "original-policy": "default-src 'self'; img-src 'self' https://img.example.com",
                "disposition": "enforce",
                "blocked-uri": "https://evil.com/malicious-image.png",
                "line-number": 10,
                "source-file": "https://example.com/foo/bar.html",
                "status-code": 0,
                "script-sample": "",
            }
        }

        response = self.client.post(
            f"/report?token={self.team.api_token}",
            data=json.dumps(csp_report),
            content_type="application/csp-report",
        )
        assert status.HTTP_204_NO_CONTENT == response.status_code
        assert mock_capture.call_count == 1

    def test_capture_csp_invalid_json_gives_invalid_csp_payload(self):
        response = self.client.post(
            f"/report/?token={self.team.api_token}",
            data="this is not valid json",
            content_type="application/csp-report",
        )

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert "Invalid CSP report format" in response.json()["detail"]
        assert response.json()["code"] == "invalid_csp_payload"

    def test_capture_csp_invalid_report_format_gives_invalid_csp_payload(self):
        invalid_csp_report = {"not-a-csp-report": "invalid format"}

        response = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(invalid_csp_report),
            content_type="application/csp-report",
        )

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert "Invalid CSP report properties provided" in response.json()["detail"]
        assert response.json()["code"] == "invalid_csp_payload"

    def test_integration_csp_report_invalid_json_gives_invalid_csp_payload(self):
        response = self.client.post(
            f"/report/?token={self.team.api_token}",
            data="this is not valid json}",
            content_type="application/csp-report",
        )

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert "Invalid CSP report format" in response.json()["detail"]
        assert response.json()["code"] == "invalid_csp_payload"

    def test_integration_csp_report_invalid_format(self):
        invalid_format = {
            "not-a-csp-report-field": {
                "document-uri": "https://example.com/foo/bar",
            }
        }

        response = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(invalid_format),
            content_type="application/csp-report",
        )

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert "Invalid CSP report properties provided" in response.json()["detail"]
        assert response.json()["code"] == "invalid_csp_payload"

    def test_integration_csp_report_sent_as_json_without_content_type_is_handled_as_regular_event(self):
        valid_csp_report = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "violated-directive": "default-src self",
                "blocked-uri": "https://evil.com/malicious-image.png",
            }
        }

        response = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(valid_csp_report),
            content_type="application/json",  # Not application/csp-report
        )

        assert status.HTTP_400_BAD_REQUEST == response.status_code
        assert response.json()["code"] == "invalid_payload"
        assert "Failed to submit CSP report" in response.json()["detail"]

    @patch("posthog.api.report.capture_batch_internal")
    def test_integration_csp_report_with_report_to_format_returns_204(self, mock_capture):
        mock_capture.return_value = MagicMock(raise_for_status=MagicMock())

        report_to_format = [
            {
                "type": "csp-violation",
                "body": {
                    "documentURL": "https://example.com/foo/bar",
                    "referrer": "https://www.google.com/",
                    "effectiveDirective": "img-src",
                    "originalPolicy": "default-src 'self'; img-src 'self' https://img.example.com",
                    "disposition": "enforce",
                    "blockedURL": "https://evil.com/malicious-image.png",
                    "lineNumber": 10,
                    "sourceFile": "https://example.com/foo/bar.html",
                    "statusCode": 0,
                    "sample": "",
                },
            }
        ]

        response = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(report_to_format),
            content_type="application/reports+json",
        )
        assert status.HTTP_204_NO_CONTENT == response.status_code
        assert response.content == b""
        mock_capture.assert_called_once()

    @patch("posthog.api.report.capture_batch_internal")
    def test_capture_csp_report_to_violation(self, mock_capture):
        mock_capture.return_value = MagicMock(raise_for_status=MagicMock())

        report_to_format = [
            {
                "age": 53531,
                "body": {
                    "blockedURL": "inline",
                    "columnNumber": 39,
                    "disposition": "enforce",
                    "documentURL": "https://example.com/csp-report-1",
                    "effectiveDirective": "script-src-elem",
                    "lineNumber": 121,
                    "originalPolicy": "default-src 'self'; report-to csp-endpoint-name",
                    "referrer": "https://www.google.com/",
                    "sample": 'console.log("lo")',
                    "sourceFile": "https://example.com/csp-report-1",
                    "statusCode": 200,
                },
                "type": "csp-violation",
                "url": "https://example.com/csp-report-1",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
            },
            {
                "age": 12345,
                "body": {
                    "blockedURL": "https://malicious-site.com/script.js",
                    "columnNumber": 15,
                    "disposition": "enforce",
                    "documentURL": "https://example.com/csp-report-2",
                    "effectiveDirective": "script-src",
                    "lineNumber": 42,
                    "originalPolicy": "default-src 'self'; script-src 'self'; report-to csp-endpoint-name",
                    "referrer": "https://another-site.com/",
                    "sample": "",
                    "sourceFile": "https://example.com/csp-report-2",
                    "statusCode": 200,
                },
                "type": "csp-violation",
                "url": "https://example.com/csp-report-2",
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            },
        ]

        response = self.client.post(
            f"/report/?token={self.team.api_token}",
            data=json.dumps(report_to_format),
            content_type="application/reports+json",
        )
        assert status.HTTP_204_NO_CONTENT == response.status_code
        # Both events go through a single batched dispatch call
        mock_capture.assert_called_once()
        assert len(mock_capture.call_args.kwargs["events"]) == 2

    def test_csp_sampled_out_report_uri_does_not_return_400(self):
        csp_report = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "violated-directive": "default-src self",
            }
        }

        # Use 0% sampling rate to ensure report is sampled out
        response = self.client.post(
            f"/report/?token={self.team.api_token}&sample_rate=0.0",
            data=json.dumps(csp_report),
            content_type="application/csp-report",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_csp_sampled_out_report_to_does_not_return_400(self):
        report_to_format = [
            {
                "type": "csp-violation",
                "body": {
                    "documentURL": "https://example.com/foo/bar",
                    "effectiveDirective": "script-src",
                },
            }
        ]

        # Use 0% sampling rate to ensure report is sampled out
        response = self.client.post(
            f"/report/?token={self.team.api_token}&sample_rate=0.0",
            data=json.dumps(report_to_format),
            content_type="application/reports+json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @patch("posthog.api.report.capture_internal")
    def test_safari_single_csp_violation_with_csp_report_content_type(self, mock_capture):
        mock_capture.return_value = MagicMock(status_code=204)

        safari_report = {
            "type": "csp-violation",
            "url": "https://us.posthog.com/signup?next=%2F&__posthog.debug=true",
            "body": {
                "documentURL": "https://us.posthog.com/signup?next=%2F&__posthog.debug=true",
                "disposition": "report",
                "referrer": "",
                "effectiveDirective": "script-src-elem",
                "blockedURL": "inline",
                "originalPolicy": "default-src 'self'; style-src 'self' 'unsafe-inline' https://*.posthog.com",
                "statusCode": 200,
                "sample": "",
                "sourceFile": "https://us.posthog.com/signup?next=%2F&__posthog.debug=true",
                "lineNumber": 53,
                "columnNumber": 1,
            },
        }

        response = self.client.post(
            f"/report/?token={self.team.api_token}&sample_rate=1.0&v=2",
            data=json.dumps(safari_report),
            content_type="application/csp-report",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_capture.assert_called_once()
