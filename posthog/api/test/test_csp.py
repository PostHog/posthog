from html import escape
import json

from django.test import TestCase
from django.test.client import RequestFactory

from posthog.api.csp import (
    process_csp_report,
    parse_report_uri,
    parse_report_to,
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

        assert properties["$current_url"] == "https://example.com/foo/bar"
        assert properties["violated_directive"] == "default-src self"
        assert properties["blocked_url"] == "https://evil.com/malicious-image.png"
        assert properties["script_sample"] == escape("alert('hello')")

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
                "sample": "<script>console.log('test')</script>",
            },
        }

        properties = parse_report_to(data)

        assert properties["$current_url"] == "https://example.com/page.html"
        assert properties["user_agent"] == "Mozilla/5.0"
        assert properties["script_sample"] == escape("<script>console.log('test')</script>")
        assert properties["violated_directive"] == "script-src-elem"

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
                "column-number": 10,
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
        assert uri_properties["$current_url"] == "https://example.com/page"
        assert to_properties["$current_url"] == "https://example.com/page"

        assert uri_properties["referrer"] == "https://referrer.example.com"
        assert to_properties["referrer"] == "https://referrer.example.com"

        # report-uri has violated_directive directly
        assert uri_properties["violated_directive"] == "script-src 'self'"

        # Both formats have effective_directive field
        assert uri_properties["effective_directive"] == "script-src"
        assert to_properties["effective_directive"] == "script-src"

        # Original policy should be preserved in both
        assert uri_properties["original_policy"] == "default-src 'self'; script-src 'self'"
        assert to_properties["original_policy"] == "default-src 'self'; script-src 'self'"

        # Disposition should be the same
        assert uri_properties["disposition"] == "enforce"
        assert to_properties["disposition"] == "enforce"

        # Blocked URL is normalized
        assert uri_properties["blocked_url"] == "https://blocked.example.com/script.js"
        assert to_properties["blocked_url"] == "https://blocked.example.com/script.js"

        # Line number is preserved
        assert uri_properties["line_number"] == 42
        assert to_properties["line_number"] == 42

        # Column number only exists in report-to format
        assert to_properties["column_number"] == 10
        assert uri_properties["column_number"] == 10

        # Source file is normalized
        assert uri_properties["source_file"] == "https://example.com/source.js"
        assert to_properties["source_file"] == "https://example.com/source.js"

        # Status code is preserved
        assert uri_properties["status_code"] == 200
        assert to_properties["status_code"] == 200

        # Script sample is preserved in both
        assert uri_properties["script_sample"] == escape("alert('uri-format')")
        assert to_properties["script_sample"] == escape("alert('to-format')")

        # User agent is only in report-to format
        assert to_properties["user_agent"] == "Mozilla/5.0 (Example Browser)"
        assert "user_agent" not in uri_properties

        # Report type is preserved in both
        assert uri_properties["report_type"] == "csp-violation"
        assert to_properties["report_type"] == "csp-violation"

    def test_parse_modern_report_to_format(self):
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

        assert properties["$current_url"] == "https://example.com/csp-report"
        assert (
            properties["user_agent"]
            == "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        )
        assert properties["blocked_url"] == "inline"  # Verify standard field name
        assert properties["script_sample"] == escape('console.log("lo")')
        assert properties["raw_report"]["age"] == 53531
        assert properties["effective_directive"] == "script-src-elem"  # Verify standardized field name
        assert properties["status_code"] == 200  # Verify standard field name

    def test_parse_report_to_with_varied_blocked_uris(self):
        # Test with 'eval' blocked URI
        eval_data = {"body": {"blockedURL": "eval", "documentURL": "https://example.com/page"}, "type": "csp-violation"}
        eval_properties = parse_report_to(eval_data)
        assert eval_properties["blocked_url"] == "eval"

        # Test with 'inline' blocked URI
        inline_data = {
            "body": {"blockedURL": "inline", "documentURL": "https://example.com/page"},
            "type": "csp-violation",
        }
        inline_properties = parse_report_to(inline_data)
        assert inline_properties["blocked_url"] == "inline"

        # Test with data: URI
        data_uri_data = {
            "body": {"blockedURL": "data:image/png;base64,iVBORw0KGg", "documentURL": "https://example.com/page"},
            "type": "csp-violation",
        }
        data_uri_properties = parse_report_to(data_uri_data)
        assert data_uri_properties["blocked_url"] == "data:image/png;base64,iVBORw0KGg"

    def test_parse_report_to_with_url_fallbacks(self):
        # Test with document-uri instead of documentURL
        data1 = {
            "body": {"document-uri": "https://example.com/page1", "blocked-uri": "inline"},
            "type": "csp-violation",
        }
        properties1 = parse_report_to(data1)
        assert properties1["$current_url"] == "https://example.com/page1"

        # Test with url field instead of documentURL (and no document-uri)
        data2 = {"body": {"blocked-uri": "inline"}, "type": "csp-violation", "url": "https://example.com/page1"}
        properties2 = parse_report_to(data2)
        assert properties2["$current_url"] == "https://example.com/page1"

        # Test with no URL fields at all
        data3 = {"body": {"blocked-uri": "inline"}, "type": "csp-violation"}
        properties3 = parse_report_to(data3)
        assert properties3["$current_url"] is None

    def test_parse_report_to_with_multiple_script_samples(self):
        data = {
            "body": {
                "documentURL": "https://example.com/page",
                "sample": "alert('test')",
            },
            "type": "csp-violation",
        }

        properties = parse_report_to(data)

        assert properties["script_sample"] == escape("alert('test')")

    def test_process_csp_report_from_query_params(self):
        csp_data = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "violated-directive": "default-src self",
            }
        }

        request = self.factory.post(
            "/csp/?distinct_id=test-user&session_id=test-session&v=1",
            data=json.dumps(csp_data),
            content_type="application/csp-report",
        )

        event, _ = process_csp_report(request)

        assert event["distinct_id"] == "test-user"
        assert event["properties"]["$session_id"] == "test-session"
        assert event["properties"]["csp_version"] == "1"
