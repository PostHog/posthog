import json
from datetime import datetime
from html import escape

from freezegun import freeze_time
from unittest.mock import patch

from django.test import TestCase
from django.test.client import RequestFactory

from posthog.api.csp import parse_report_to, parse_report_uri, process_csp_report, sample_csp_report
from posthog.sampling import sample_on_property


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

        assert properties["document_url"] == "https://example.com/foo/bar"
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

        assert properties["document_url"] == "https://example.com/page.html"
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
        assert uri_properties["document_url"] == "https://example.com/page"
        assert to_properties["document_url"] == "https://example.com/page"

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

        assert properties["document_url"] == "https://example.com/csp-report"
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
        assert properties1["document_url"] == "https://example.com/page1"

        # Test with url field instead of documentURL (and no document-uri)
        data2 = {"body": {"blocked-uri": "inline"}, "type": "csp-violation", "url": "https://example.com/page1"}
        properties2 = parse_report_to(data2)
        assert properties2["document_url"] == "https://example.com/page1"

        # Test with no URL fields at all
        data3 = {"body": {"blocked-uri": "inline"}, "type": "csp-violation"}
        properties3 = parse_report_to(data3)
        assert properties3["document_url"] is None

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
        assert event["properties"]["$csp_version"] == "1"

    @freeze_time("2023-01-01 12:00:00")
    def test_sample_csp_report(self):
        trunc_date_iso_format = datetime(2023, 1, 1, 12, 0, 0).isoformat()

        properties = {
            "document_url": "https://example.com/page",
            "effective_directive": "script-src",
        }

        # Test at 100% sampling rate
        assert sample_csp_report(properties, 1.0) is True

        # Test at 0% sampling rate
        assert sample_csp_report(properties, 0.0) is False

        # Test deterministic behavior
        result_at_50_percent = sample_csp_report(properties, 0.5)
        # The same properties should have the same sampling decision at the same rate
        assert sample_csp_report(properties, 0.5) is result_at_50_percent

        # Test with missing document_url
        assert sample_csp_report({"effective_directive": "script-src"}, 0.5) == sample_on_property(
            f"-{trunc_date_iso_format}", 0.5
        )

        # Test with only document_url
        assert sample_csp_report({"document_url": "https://example.com/page"}, 0.5) == sample_on_property(
            f"https://example.com/page-{trunc_date_iso_format}", 0.5
        )

    def test_process_csp_report_with_sampling_in(self):
        # Create a test properties dictionary
        properties = {
            "document_url": "https://example.com/foo/bar",
            "effective_directive": "script-src",
        }

        # Test without adding metadata (add_metadata=False)
        result = sample_csp_report(properties, 0.5, False)
        assert isinstance(result, bool)
        assert "csp_sampled" not in properties
        assert "csp_sample_threshold" not in properties

        # Test with 100% sampling rate (should not add metadata)
        properties = {
            "document_url": "https://example.com/foo/bar",
            "effective_directive": "script-src",
        }
        result = sample_csp_report(properties, 1.0, True)
        assert result is True

    def test_sampling_determinism_across_report_types(self):
        """Test that sampling is deterministic across different report formats for the same content"""
        report_uri_data = {
            "csp-report": {
                "document-uri": "https://example.com/test-page",
                "effective-directive": "script-src",
            }
        }

        report_to_data = {
            "type": "csp-violation",
            "body": {
                "documentURL": "https://example.com/test-page",
                "effectiveDirective": "script-src",
            },
        }

        # Parse both reports
        uri_properties = parse_report_uri(report_uri_data)
        to_properties = parse_report_to(report_to_data)

        # They should have the same sampling decision at the same sampling rate
        for rate in [0.1, 0.5, 0.9]:
            assert sample_csp_report(uri_properties, rate) == sample_csp_report(to_properties, rate)

    def test_sampling_consistency_over_range(self):
        """Test that sampling decisions remain consistent for the same inputs"""
        properties = {
            "document_url": "https://example.com/page",
            "effective_directive": "script-src",
        }

        # Record sampling decisions at different rates
        decisions = {}
        for rate in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            decisions[rate] = sample_csp_report(properties, rate)

        # Now check that the decisions are the same in a second pass
        for rate in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            assert sample_csp_report(properties, rate) == decisions[rate]

    def test_sampling_different_urls_same_directive(self):
        urls = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.org/page1",
            "https://subdomain.example.com/",
            "http://example.com/page1",  # Different protocol
            "https://example.com/page1?query=param",  # With query parameters
            "https://example.com/page1#section",  # With fragment
        ]

        directive = "script-src"
        rate = 0.5

        # Each URL should have its own sampling decision
        results = {}
        for url in urls:
            properties = {"document_url": url, "effective_directive": directive}
            results[url] = sample_csp_report(properties, rate)

        # Check that the results are a mix of True and False (not all same decision for 0.5 rate)
        assert (
            True in results.values() and False in results.values()
        ), "Expected some URLs to be sampled in and some out"

        # Each URL should have a consistent sampling decision
        for url in urls:
            properties = {"document_url": url, "effective_directive": directive}
            assert sample_csp_report(properties, rate) == results[url]

    def test_sampling_same_url_different_directives(self):
        url = "https://example.com/page"
        directives = [
            "script-src",
            "style-src",
            "img-src",
            "connect-src",
            "font-src",
            "media-src",
            "object-src",
            "prefetch-src",
        ]

        rate = 0.5

        # All directives should have the same sampling decision for the same URL (aka: we should receive all reports for the same URL)
        # Initialize with the first directive's result
        properties = {"document_url": url, "effective_directive": directives[0]}
        first_result = sample_csp_report(properties, rate)

        # Then check all directives have the same result
        for directive in directives:
            properties = {"document_url": url, "effective_directive": directive}
            result = sample_csp_report(properties, rate)
            assert (
                result == first_result
            ), f"Expected same sampling decision for same URL regardless of directive, got {result} vs {first_result}"

    def test_edge_case_urls_and_directives(self):
        """Test sampling with edge case URLs and directives"""
        edge_cases = [
            # Empty URL
            {"document_url": "", "effective_directive": "script-src"},
            # Very long URL
            {"document_url": "https://example.com/" + "a" * 1000, "effective_directive": "script-src"},
            # URL with special characters
            {"document_url": "https://example.com/?q=test&param=value#fragment", "effective_directive": "script-src"},
            # Unicode URL
            {"document_url": "https://example.com/你好世界", "effective_directive": "script-src"},
            # Empty directive
            {"document_url": "https://example.com/", "effective_directive": ""},
            # Non-standard directive
            {"document_url": "https://example.com/", "effective_directive": "custom-directive"},
            # Both empty
            {"document_url": "", "effective_directive": ""},
        ]

        rate = 0.5

        # Each case should have a deterministic sampling decision
        for case in edge_cases:
            result1 = sample_csp_report(case, rate)
            result2 = sample_csp_report(case, rate)
            assert result1 == result2, f"Expected consistent sampling decision for {case}"

    def test_process_csp_report_with_sampling_out(self):
        properties = {
            "document_url": "https://example.com/foo/bar",
            "effective_directive": "script-src",
        }

        # Test with 0% sampling rate (should be sampled out)
        result = sample_csp_report(properties, 0.0, True)
        assert not result

    @patch("posthog.api.csp.logger")
    def test_process_csp_report_logs_invalid_content_type(self, mock_logger):
        """Test that invalid content type is logged"""
        request = self.factory.post(
            "/report/",
            data='{"test": "data"}',
            content_type="application/json",  # Invalid content type
        )

        result, error = process_csp_report(request)

        assert result is None
        assert error is None
        mock_logger.warning.assert_called_once_with(
            "CSP report skipped - invalid content type",
            content_type="application/json",
            expected_types=["application/csp-report", "application/reports+json"],
        )

    @patch("posthog.api.csp.logger")
    def test_process_csp_report_logs_sampling_out_report_uri(self, mock_logger):
        """Test that sampling out is logged for report-uri format"""
        csp_data = {
            "csp-report": {
                "document-uri": "https://example.com/foo/bar",
                "violated-directive": "default-src self",
            }
        }

        request = self.factory.post(
            "/report/?sample_rate=0.0",  # 0% sampling rate
            data=json.dumps(csp_data),
            content_type="application/csp-report",
        )

        result, error = process_csp_report(request)

        assert result is None
        assert error.status_code == 204
        mock_logger.warning.assert_called_with(
            "CSP report sampled out - report-uri format",
            document_url="https://example.com/foo/bar",
            sample_rate=0.0,
        )

    @patch("posthog.api.csp.logger")
    def test_process_csp_report_logs_sampling_out_report_to(self, mock_logger):
        """Test that sampling out is logged for report-to format"""
        report_to_data = [
            {
                "type": "csp-violation",
                "body": {
                    "documentURL": "https://example.com/foo/bar",
                    "effectiveDirective": "script-src",
                },
            }
        ]

        request = self.factory.post(
            "/report/?sample_rate=0.0",  # 0% sampling rate
            data=json.dumps(report_to_data),
            content_type="application/reports+json",
        )

        result, error = process_csp_report(request)

        assert result is None
        assert error.status_code == 204
        mock_logger.warning.assert_called_with(
            "CSP report sampled out - report-to format",
            total_violations=1,
            sample_rate=0.0,
        )

    @patch("posthog.api.csp.logger")
    def test_process_csp_report_logs_json_decode_error(self, mock_logger):
        """Test that JSON decode errors are logged as exceptions"""
        request = self.factory.post(
            "/report/",
            data="invalid json",
            content_type="application/csp-report",
        )

        result, error = process_csp_report(request)

        assert result is None
        assert error is not None  # Should return error response
        mock_logger.exception.assert_called_once()
        call_args = mock_logger.exception.call_args
        assert call_args[0][0] == "Invalid CSP report JSON format"
        assert "error" in call_args[1]

    @patch("posthog.api.csp.logger")
    def test_process_csp_report_logs_value_error(self, mock_logger):
        """Test that value errors are logged as exceptions"""
        # Create invalid CSP data that will trigger ValueError
        invalid_data = {"invalid": "data"}

        request = self.factory.post(
            "/report/",
            data=json.dumps(invalid_data),
            content_type="application/csp-report",
        )

        result, error = process_csp_report(request)

        assert result is None
        assert error is not None  # Should return error response
        mock_logger.exception.assert_called_once()
        call_args = mock_logger.exception.call_args
        assert call_args[0][0] == "Invalid CSP report properties"
        assert "error" in call_args[1]

    def test_dynamic_sampling_with_time_component_includes_url_and_time(self):
        """Test that the sampling key includes both URL and time component"""
        properties = {
            "document_url": "https://example.com/page",
            "effective_directive": "script-src",
        }

        # First minute
        with freeze_time("2023-01-01 12:00:00"):
            properties_copy1 = properties.copy()
            sample_csp_report(properties_copy1, 0.5, add_metadata=True)
            sampling_key1 = properties_copy1.get("csp_sampling_key")

        # Second minute
        with freeze_time("2023-01-01 12:01:00"):
            properties_copy2 = properties.copy()
            sample_csp_report(properties_copy2, 0.5, add_metadata=True)
            sampling_key2 = properties_copy2.get("csp_sampling_key")

        # Verify sampling keys are different due to time component
        assert sampling_key1 != sampling_key2
        assert sampling_key1 is not None and "2023-01-01T12:00:00" in sampling_key1
        assert sampling_key2 is not None and "2023-01-01T12:01:00" in sampling_key2

        # Both should contain the URL
        assert sampling_key1 is not None and "https://example.com/page" in sampling_key1
        assert sampling_key2 is not None and "https://example.com/page" in sampling_key2

    @freeze_time("2023-01-01 12:00:00")
    def test_sampling_consistency_within_same_minute(self):
        properties1 = {
            "document_url": "https://example.com/page",
            "effective_directive": "script-src",
        }

        properties2 = {
            "document_url": "https://example.com/page",
            "effective_directive": "img-src",  # Different directive, same URL
        }

        # Sample both within the same minute
        result1 = sample_csp_report(properties1, 0.5, add_metadata=True)
        result2 = sample_csp_report(properties2, 0.5, add_metadata=True)

        # Should have the same sampling decision since it's the same URL and same minute
        assert result1 == result2

        # Should have the same sampling key (URL + time)
        assert properties1["csp_sampling_key"] == properties2["csp_sampling_key"]

    def test_same_url_different_sampling_across_time_windows(self):
        """Test that demonstrates URLs are not permanently excluded

        Uses deterministic test cases based on known hash outcomes to ensure robustness.
        This test proves that the same URL can be both sampled in AND out across different time windows.
        """

        # Test specific URL+time combinations with known expected outcomes
        # These were determined by calculating hash(url + "-" + timestamp) % 100
        deterministic_test_cases = [
            # URL, time_string, expected_result_at_50_percent, hash_mod_100
            ("https://example.com/other", "2023-01-01 12:00:00", True, 8),  # 8 < 50 = True
            ("https://example.com/other", "2023-01-01 12:01:00", False, 99),  # 99 >= 50 = False
            ("https://test.com/page", "2023-01-01 12:03:00", False, 52),  # 52 >= 50 = False
            ("https://test.com/page", "2023-01-01 12:04:00", True, 43),  # 43 < 50 = True
            ("https://test.com/page", "2023-01-01 12:09:00", False, 98),  # 98 >= 50 = False
        ]

        for url, time_string, expected_result, expected_hash_mod in deterministic_test_cases:
            with freeze_time(time_string):
                properties = {"document_url": url, "effective_directive": "script-src"}
                result = sample_csp_report(properties, 0.5)
                assert (
                    result == expected_result
                ), f"Expected {expected_result} for {url} at {time_string} (hash%100={expected_hash_mod}), got {result}"

        # Demonstrate the key improvement: same URL gets different sampling decisions across time
        url = "https://test.com/page"
        time_sampling_pairs = [
            ("2023-01-01 12:03:00", False),  # hash%100=52 >= 50
            ("2023-01-01 12:04:00", True),  # hash%100=43 < 50
            ("2023-01-01 12:09:00", False),  # hash%100=98 >= 50
        ]

        sampled_in_results = []
        sampled_out_results = []

        for time_string, expected_result in time_sampling_pairs:
            with freeze_time(time_string):
                properties = {"document_url": url, "effective_directive": "script-src"}
                result = sample_csp_report(properties, 0.5)
                assert result == expected_result, f"Failed deterministic test for {url} at {time_string}"

                if result:
                    sampled_in_results.append(time_string)
                else:
                    sampled_out_results.append(time_string)

        # This is the key assertion: same URL gets BOTH outcomes across time windows
        assert len(sampled_in_results) > 0, f"URL {url} should be sampled IN at least once"
        assert len(sampled_out_results) > 0, f"URL {url} should be sampled OUT at least once"

        # Verify consistency within the same minute (time component doesn't change within a minute)
        with freeze_time("2023-01-01 12:00:00"):
            properties1 = {"document_url": "https://example.com/test", "effective_directive": "script-src"}
            result1 = sample_csp_report(properties1.copy(), 0.5)
            result2 = sample_csp_report(properties1.copy(), 0.5)

            assert result1 == result2, "Same URL+time should produce consistent sampling results within the same minute"
