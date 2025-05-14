import json
from unittest.mock import patch

from django.test import TestCase
from django.test.client import RequestFactory
from rest_framework import status

from posthog.api.csp import (
    process_csp_report,
    parse_report_uri,
    parse_report_to,
    parse_properties,
)


class TestCSPModule(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_parse_report_uri(self):
        """Test parsing CSP report in report-uri format"""
        data = {
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

        properties = parse_report_uri(data)

        # Verify current_url is parsed correctly
        self.assertEqual(properties["$current_url"], "https://example.com/foo/bar")
        # Verify other properties are included
        self.assertEqual(properties["violated-directive"], "default-src self")
        self.assertEqual(properties["blocked-uri"], "https://evil.com/malicious-image.png")
        self.assertEqual(properties["script-sample"], "alert('hello')")

    def test_parse_report_to(self):
        """Test parsing CSP report in report-to format"""
        data = {
            "type": "csp-violation",
            "report-to": "csp-endpoint",
            "body": {
                "documentURL": "https://example.com/page.html",
                "user-agent": "Mozilla/5.0",
                "blocked-uri": "https://evil.com/script.js",
                "disposition": "enforce",
                "violated-directive": "script-src-elem",
                "sample": "console.log('test')",
            },
        }

        properties = parse_report_to(data)

        # Verify current_url is parsed correctly
        self.assertEqual(properties["$current_url"], "https://example.com/page.html")
        # Verify user-agent is preserved
        self.assertEqual(properties["$user_agent"], "Mozilla/5.0")
        # Verify report-to field is preserved
        self.assertEqual(properties["$report_to"], "csp-endpoint")
        # Verify script sample is redacted
        self.assertEqual(properties["sample"], "REDACTED")
        # Verify other properties are included
        self.assertEqual(properties["violated-directive"], "script-src-elem")

    def test_parse_modern_report_to_format(self):
        """Test parsing modern CSP report in report-to format with fields at different levels"""
        data = {
            "age": 53531,
            "body": {
                "blockedURL": "inline",
                "columnNumber": 39,
                "disposition": "enforce",
                "documentURL": "https://example.com/csp-report",
                "effectiveDirective": "script-src-elem",
                "lineNumber": 121,
                "originalPolicy": "default-src 'self'; report-to csp-endpoint-name",
                "referrer": "https://www.google.com/",
                "sample": 'console.log("lo")',
                "sourceFile": "https://example.com/csp-report",
                "statusCode": 200,
            },
            "type": "csp-violation",
            "url": "https://example.com/csp-report",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        }

        properties = parse_report_to(data)

        # Verify properties are parsed correctly
        self.assertEqual(properties["$current_url"], "https://example.com/csp-report")
        self.assertEqual(
            properties["$user_agent"],
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        )
        self.assertEqual(properties["blocked-uri"], "inline")  # Verify camelCase conversion
        self.assertEqual(properties["sample"], "REDACTED")  # Verify sample redaction
        self.assertEqual(properties["age"], 53531)  # Verify age is correctly included
        self.assertEqual(properties["effectiveDirective"], "script-src-elem")  # Verify original camelCase fields remain
        self.assertEqual(properties["statusCode"], 200)  # Verify status code

    def test_parse_properties_invalid_report(self):
        """Test handling of invalid CSP report formats"""
        data = {"not-a-valid-report": True}

        with self.assertRaises(ValueError):
            parse_properties(data)

    @patch("posthog.api.csp.uuid7")
    def test_process_csp_report_generates_ids(self, mock_uuid7):
        """Test that distinct_id and session_id are generated if not provided"""
        # Create two different mock UUIDs for the two calls
        mock_uuid7.side_effect = ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]

        csp_data = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "violated-directive": "default-src self",
            }
        }

        request = self.factory.post("/csp/", data=json.dumps(csp_data), content_type="application/csp-report")

        # Process the report
        event, error_response = process_csp_report(request)

        # Verify IDs were generated
        self.assertEqual(event["distinct_id"], "00000000-0000-0000-0000-000000000001")
        self.assertEqual(event["session_id"], "00000000-0000-0000-0000-000000000002")
        self.assertEqual(event["version"], "unknown")

        # Verify mock was called twice (once for distinct_id, once for session_id)
        self.assertEqual(mock_uuid7.call_count, 2)

    def test_process_csp_report_with_provided_ids(self):
        """Test that distinct_id and session_id from query params are used"""
        csp_data = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "violated-directive": "default-src self",
            }
        }

        request = self.factory.post(
            "/csp/?distinct_id=test-user&session_id=test-session&v=1.2.3",
            data=json.dumps(csp_data),
            content_type="application/csp-report",
        )

        # Process the report
        event, error_response = process_csp_report(request)

        # Verify provided IDs were used
        self.assertEqual(event["distinct_id"], "test-user")
        self.assertEqual(event["session_id"], "test-session")
        self.assertEqual(event["version"], "1.2.3")

    def test_process_csp_report_json_decode_error(self):
        """Test handling of JSON parsing errors"""
        request = self.factory.post("/csp/", data="not valid json", content_type="application/csp-report")

        # Process the report
        _, error_response = process_csp_report(request)

        # Verify error response
        self.assertIsNotNone(error_response)
        self.assertEqual(error_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_process_csp_report_skips_non_csp_content_type(self):
        """Test early return for non-CSP content types"""
        request = self.factory.post("/csp/", data=json.dumps({"some": "data"}), content_type="application/json")

        # Process the report
        event, error_response = process_csp_report(request)

        # Verify no processing was done
        self.assertIsNone(event)
        self.assertIsNone(error_response)
