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

    def test_format_comparison_parsing(self):
        """
        Test the parsing of both report-to and report-uri formats according to the field mapping table.

        This test verifies that fields from both formats are correctly normalized.
        """
        # Create a report in report-uri format with all fields from the table
        report_uri_data = {
            "csp-report": {
                "document-uri": "https://example.com/page",
                "referrer": "https://referrer.example.com",
                "violated-directive": "script-src 'self'",
                "effective-directive": "script-src",
                "original-policy": "default-src 'self'; script-src 'self'",
                "disposition": "enforce",
                "blocked-uri": "https://blocked.example.com/script.js",
                "line-number": 42,
                "source-file": "https://example.com/source.js",
                "status-code": 200,
                "script-sample": "alert('uri-format')",
            }
        }

        # Create a report in report-to format with all fields from the table
        report_to_data = {
            "type": "csp-violation",
            "report-to": "csp-endpoint",
            "user_agent": "Mozilla/5.0 (Example Browser)",
            "body": {
                "documentURL": "https://example.com/page",
                "referrer": "https://referrer.example.com",
                "effectiveDirective": "script-src",
                "originalPolicy": "default-src 'self'; script-src 'self'",
                "disposition": "enforce",
                "blockedURL": "https://blocked.example.com/script.js",
                "lineNumber": 42,
                "columnNumber": 10,  # Only in report-to format
                "sourceFile": "https://example.com/source.js",
                "statusCode": 200,
                "sample": "alert('to-format')",
            },
        }

        # Parse both formats
        uri_properties = parse_report_uri(report_uri_data)
        to_properties = parse_report_to(report_to_data)

        # Verify common fields are parsed correctly in both formats
        self.assertEqual(uri_properties["$current_url"], "https://example.com/page")
        self.assertEqual(to_properties["$current_url"], "https://example.com/page")

        self.assertEqual(uri_properties["referrer"], "https://referrer.example.com")
        self.assertEqual(to_properties["referrer"], "https://referrer.example.com")

        # report-uri has violated-directive directly
        self.assertEqual(uri_properties["violated-directive"], "script-src 'self'")

        # Both formats have effective-directive field
        self.assertEqual(uri_properties["effective-directive"], "script-src")
        self.assertEqual(to_properties["effectiveDirective"], "script-src")

        # Original policy should be preserved in both
        self.assertEqual(uri_properties["original-policy"], "default-src 'self'; script-src 'self'")
        self.assertEqual(to_properties["original-policy"], "default-src 'self'; script-src 'self'")

        # Disposition should be the same
        self.assertEqual(uri_properties["disposition"], "enforce")
        self.assertEqual(to_properties["disposition"], "enforce")

        # Blocked URI is normalized in report-to format
        self.assertEqual(uri_properties["blocked-uri"], "https://blocked.example.com/script.js")
        self.assertEqual(to_properties["blocked-uri"], "https://blocked.example.com/script.js")

        # Line number is preserved
        self.assertEqual(uri_properties["line-number"], 42)
        self.assertEqual(to_properties["lineNumber"], 42)

        # Column number only exists in report-to format
        self.assertEqual(to_properties["columnNumber"], 10)
        self.assertNotIn("column-number", uri_properties)

        # Source file is normalized
        self.assertEqual(uri_properties["source-file"], "https://example.com/source.js")
        self.assertEqual(to_properties["source-file"], "https://example.com/source.js")

        # Status code is preserved
        self.assertEqual(uri_properties["status-code"], 200)
        self.assertEqual(to_properties["statusCode"], 200)

        # Script sample is redacted in report-to format
        self.assertEqual(uri_properties["script-sample"], "alert('uri-format')")
        self.assertEqual(to_properties["sample"], "REDACTED")

        # User agent is only in report-to format
        self.assertEqual(to_properties["$user_agent"], "Mozilla/5.0 (Example Browser)")
        self.assertNotIn("$user_agent", uri_properties)

        # Report type is preserved in report-to format
        self.assertEqual(to_properties["$report_to"], "csp-endpoint")
        self.assertNotIn("$report_to", uri_properties)

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

    def test_parse_report_to_with_report_id(self):
        """Test parsing report-to format with report_id field"""
        data = {
            "age": 42,
            "body": {
                "blockedURL": "eval",
                "disposition": "enforce",
                "documentURL": "https://app.example.com/dashboard",
                "effectiveDirective": "script-src-elem",
                "originalPolicy": "script-src 'self'; object-src 'none'",
                "referrer": "https://app.example.com/",
                "sourceFile": "https://app.example.com/bundle.js",
            },
            "type": "csp-violation",
            "report_id": "abcdef-123456-ghijkl",
            "url": "https://app.example.com/dashboard",
        }

        properties = parse_report_to(data)

        # Verify report_id is included
        self.assertEqual(properties["report_id"], "abcdef-123456-ghijkl")
        # Verify blockedURL is properly converted to blocked-uri
        self.assertEqual(properties["blocked-uri"], "eval")
        # Verify URL fallback when document-uri is not available
        self.assertEqual(properties["$current_url"], "https://app.example.com/dashboard")

    def test_parse_report_to_with_varied_blocked_uris(self):
        """Test parsing report-to format with different blocked URI patterns"""
        # Test with 'eval' blocked URI
        eval_data = {"body": {"blockedURL": "eval", "documentURL": "https://example.com/page"}, "type": "csp-violation"}
        eval_properties = parse_report_to(eval_data)
        self.assertEqual(eval_properties["blocked-uri"], "eval")

        # Test with 'inline' blocked URI
        inline_data = {
            "body": {"blockedURL": "inline", "documentURL": "https://example.com/page"},
            "type": "csp-violation",
        }
        inline_properties = parse_report_to(inline_data)
        self.assertEqual(inline_properties["blocked-uri"], "inline")

        # Test with data: URI
        data_uri_data = {
            "body": {"blockedURL": "data:image/png;base64,iVBORw0KGg", "documentURL": "https://example.com/page"},
            "type": "csp-violation",
        }
        data_uri_properties = parse_report_to(data_uri_data)
        self.assertEqual(data_uri_properties["blocked-uri"], "data:image/png;base64,iVBORw0KGg")

    def test_parse_report_to_with_url_fallbacks(self):
        """Test parsing report-to format with different URL field locations"""
        # Test with document-uri instead of documentURL
        data1 = {
            "body": {"document-uri": "https://example.com/page1", "blocked-uri": "inline"},
            "type": "csp-violation",
        }
        properties1 = parse_report_to(data1)
        self.assertEqual(properties1["$current_url"], "https://example.com/page1")

        # Test with url field instead of documentURL (and no document-uri)
        data2 = {"body": {"blocked-uri": "inline"}, "type": "csp-violation", "url": "https://example.com/page2"}
        properties2 = parse_report_to(data2)
        self.assertEqual(properties2["$current_url"], "https://example.com/page2")

        # Test with no URL fields at all
        data3 = {"body": {"blocked-uri": "inline"}, "type": "csp-violation"}
        properties3 = parse_report_to(data3)
        self.assertIsNone(properties3["$current_url"])

    def test_parse_report_to_with_multiple_script_samples(self):
        """Test proper handling of multiple sample fields in report-to format"""
        data = {
            "body": {
                "documentURL": "https://example.com/page",
                "sample": "alert('test')",
                "script-sample": "console.log('another test')",
                "sourceCodeExample": "document.write('<script>x=1</script>')",
            },
            "type": "csp-violation",
        }

        properties = parse_report_to(data)

        # Verify all script samples are redacted
        self.assertEqual(properties["sample"], "REDACTED")
        self.assertEqual(properties["script-sample"], "REDACTED")
        self.assertEqual(properties["sourceCodeExample"], "REDACTED")

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
