from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2

from ee.hogai.context.error_tracking.context import ErrorTrackingIssueContext


@freeze_time("2025-01-15T12:00:00Z")
class TestErrorTrackingIssueContext(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    distinct_id_one = "user_1"
    issue_id_one = "01936e7f-d7ff-7314-b2d4-7627981e34f0"

    def setUp(self):
        super().setUp()

        _create_person(
            team=self.team,
            distinct_ids=[self.distinct_id_one],
            is_identified=True,
        )

        self.create_events_and_issue(
            issue_id=self.issue_id_one,
            issue_name="TypeError: Cannot read property 'map' of undefined",
            fingerprint="issue_one_fingerprint",
            distinct_ids=[self.distinct_id_one],
            timestamp=now() - relativedelta(hours=3),
            exception_list=[
                {
                    "type": "TypeError",
                    "value": "Cannot read property 'map' of undefined",
                    "stacktrace": {
                        "frames": [
                            {
                                "resolved_name": "processData",
                                "source": "src/utils/data.js",
                                "line": 42,
                                "column": 15,
                                "in_app": True,
                                "context_line": "return data.map(item => item.value);",
                            },
                            {
                                "resolved_name": "handleClick",
                                "source": "src/components/Button.js",
                                "line": 28,
                                "column": 8,
                                "in_app": True,
                            },
                            {
                                "resolved_name": "onClick",
                                "source": "node_modules/react-dom/cjs/react-dom.development.js",
                                "line": 1234,
                                "in_app": False,
                            },
                        ]
                    },
                }
            ],
        )

        flush_persons_and_events()

    def create_issue(self, issue_id, fingerprint, name=None, status=ErrorTrackingIssue.Status.ACTIVE):
        issue = ErrorTrackingIssue.objects.create(id=issue_id, team=self.team, status=status, name=name)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        return issue

    def create_events_and_issue(
        self,
        issue_id,
        fingerprint,
        distinct_ids,
        timestamp=None,
        issue_name=None,
        status=ErrorTrackingIssue.Status.ACTIVE,
        exception_list=None,
    ):
        if timestamp:
            with freeze_time(timestamp):
                self.create_issue(issue_id, fingerprint, name=issue_name, status=status)
        else:
            self.create_issue(issue_id, fingerprint, name=issue_name, status=status)

        event_properties = {"$exception_issue_id": issue_id, "$exception_fingerprint": fingerprint}
        if exception_list:
            event_properties["$exception_list"] = exception_list

        for distinct_id in distinct_ids:
            _create_event(
                distinct_id=distinct_id,
                event="$exception",
                team=self.team,
                properties=event_properties,
                timestamp=timestamp,
            )

    def _create_context(self, issue_id: str, issue_name: str | None = None) -> ErrorTrackingIssueContext:
        return ErrorTrackingIssueContext(
            team=self.team,
            user=self.user,
            issue_id=issue_id,
            issue_name=issue_name,
        )

    async def test_aget_issue_returns_issue(self):
        context = self._create_context(self.issue_id_one)
        issue = await context.aget_issue()

        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual(str(issue.id), self.issue_id_one)
        self.assertEqual(issue.name, "TypeError: Cannot read property 'map' of undefined")

    async def test_aget_issue_returns_none_for_nonexistent(self):
        context = self._create_context("00000000-0000-0000-0000-000000000000")
        issue = await context.aget_issue()

        self.assertIsNone(issue)

    @patch.object(ErrorTrackingIssueContext, "_query_first_event")
    async def test_first_event_window_hit_skips_fallback(self, mock_query):
        mock_query.return_value = {"properties": {"$exception_list": []}}
        context = self._create_context(self.issue_id_one)
        first_seen = now() - relativedelta(hours=3)

        event = await context.aget_first_event(first_seen)

        self.assertIsNotNone(event)
        # Window hit → only the narrow ±1h lookup runs, no full-history fallback.
        self.assertEqual(mock_query.call_count, 1)
        window = mock_query.call_args.args[0]
        self.assertEqual(window.date_from, (first_seen - relativedelta(hours=1)).isoformat())
        self.assertEqual(window.date_to, (first_seen + relativedelta(hours=1)).isoformat())

    @patch.object(ErrorTrackingIssueContext, "_query_first_event")
    async def test_first_event_falls_back_to_all_time_when_window_misses(self, mock_query):
        mock_query.side_effect = [None, {"properties": {"$exception_list": []}}]
        context = self._create_context(self.issue_id_one)

        event = await context.aget_first_event(now() - relativedelta(hours=3))

        self.assertIsNotNone(event)
        # Window missed → second lookup spans the full history.
        self.assertEqual(mock_query.call_count, 2)
        self.assertEqual(mock_query.call_args_list[1].args[0].date_from, "all")

    @patch.object(ErrorTrackingIssueContext, "_query_first_event")
    async def test_first_event_without_first_seen_uses_all_time(self, mock_query):
        mock_query.return_value = {"properties": {"$exception_list": []}}
        context = self._create_context(self.issue_id_one)

        await context.aget_first_event(None)

        self.assertEqual(mock_query.call_count, 1)
        self.assertEqual(mock_query.call_args.args[0].date_from, "all")

    async def test_format_stacktrace_correctly(self):
        context = self._create_context(self.issue_id_one)

        event = {
            "properties": {
                "$exception_list": [
                    {
                        "type": "TypeError",
                        "value": "Cannot read property 'map' of undefined",
                        "stacktrace": {
                            "frames": [
                                {
                                    "resolved_name": "processData",
                                    "source": "src/utils/data.js",
                                    "line": 42,
                                    "column": 15,
                                    "in_app": True,
                                    "context_line": "return data.map(item => item.value);",
                                },
                                {
                                    "resolved_name": "onClick",
                                    "source": "node_modules/react-dom/cjs/react-dom.development.js",
                                    "line": 1234,
                                    "in_app": False,
                                },
                            ]
                        },
                    }
                ]
            }
        }

        stacktrace = context.format_stacktrace(event)

        assert stacktrace is not None
        self.assertIn("Exception 1: TypeError", stacktrace)
        self.assertIn("Cannot read property 'map' of undefined", stacktrace)
        self.assertIn("[IN-APP]", stacktrace)
        self.assertIn("processData", stacktrace)
        self.assertIn("src/utils/data.js:42:15", stacktrace)
        self.assertIn("return data.map(item => item.value);", stacktrace)

    async def test_format_stacktrace_returns_none_for_empty_event(self):
        context = self._create_context(self.issue_id_one)

        stacktrace = context.format_stacktrace({})
        self.assertIsNone(stacktrace)

        stacktrace = context.format_stacktrace(None)
        self.assertIsNone(stacktrace)

    async def test_format_stacktrace_returns_none_for_empty_exception_list(self):
        context = self._create_context(self.issue_id_one)

        event: dict = {"properties": {"$exception_list": []}}
        stacktrace = context.format_stacktrace(event)

        self.assertIsNone(stacktrace)

    async def test_execute_and_format_returns_error_for_nonexistent_issue(self):
        context = self._create_context("00000000-0000-0000-0000-000000000000")
        result = await context.execute_and_format()

        self.assertIn("not found", result)

    @patch.object(ErrorTrackingIssueContext, "aget_first_event")
    async def test_execute_and_format_returns_formatted_context(self, mock_get_event):
        mock_get_event.return_value = {
            "properties": {
                "$exception_list": [
                    {
                        "type": "TypeError",
                        "value": "Cannot read property 'map' of undefined",
                        "stacktrace": {
                            "frames": [
                                {
                                    "resolved_name": "processData",
                                    "source": "src/utils/data.js",
                                    "line": 42,
                                    "in_app": True,
                                }
                            ]
                        },
                    }
                ]
            }
        }

        context = self._create_context(self.issue_id_one)
        result = await context.execute_and_format()

        self.assertIn("TypeError: Cannot read property 'map' of undefined", result)
        self.assertIn("Issue ID:", result)
        self.assertIn("Stack Trace", result)
        self.assertIn("processData", result)

    @patch.object(ErrorTrackingIssueContext, "aget_first_event")
    async def test_execute_and_format_uses_provided_name(self, mock_get_event):
        mock_get_event.return_value = {
            "properties": {
                "$exception_list": [
                    {
                        "type": "Error",
                        "value": "Test",
                        "stacktrace": {
                            "frames": [
                                {
                                    "resolved_name": "test",
                                    "source": "test.js",
                                    "line": 1,
                                    "in_app": True,
                                }
                            ]
                        },
                    }
                ]
            }
        }

        context = self._create_context(self.issue_id_one, issue_name="Custom Issue Name")
        result = await context.execute_and_format()

        self.assertIn("Custom Issue Name", result)

    @patch.object(ErrorTrackingIssueContext, "aget_first_event")
    async def test_execute_and_format_returns_error_when_no_events(self, mock_get_event):
        mock_get_event.return_value = None

        context = self._create_context(self.issue_id_one)
        result = await context.execute_and_format()

        self.assertIn("No events found", result)

    @patch.object(ErrorTrackingIssueContext, "aget_first_event")
    async def test_execute_and_format_returns_error_when_no_stacktrace(self, mock_get_event):
        mock_get_event.return_value = {"properties": {"$exception_list": []}}

        context = self._create_context(self.issue_id_one)
        result = await context.execute_and_format()

        self.assertIn("No stack trace available", result)
