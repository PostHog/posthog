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
            issue_id=issue_id,
            issue_name=issue_name,
        )

    async def test_aget_issue_returns_issue(self):
        context = self._create_context(self.issue_id_one)
        issue = await context.aget_issue()

        assert issue is not None
        assert issue is not None
        assert str(issue.id) == self.issue_id_one
        assert issue.name == "TypeError: Cannot read property 'map' of undefined"

    async def test_aget_issue_returns_none_for_nonexistent(self):
        context = self._create_context("00000000-0000-0000-0000-000000000000")
        issue = await context.aget_issue()

        assert issue is None

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
        assert "Exception 1: TypeError" in stacktrace
        assert "Cannot read property 'map' of undefined" in stacktrace
        assert "[IN-APP]" in stacktrace
        assert "processData" in stacktrace
        assert "src/utils/data.js:42:15" in stacktrace
        assert "return data.map(item => item.value);" in stacktrace

    async def test_format_stacktrace_returns_none_for_empty_event(self):
        context = self._create_context(self.issue_id_one)

        stacktrace = context.format_stacktrace({})
        assert stacktrace is None

        stacktrace = context.format_stacktrace(None)
        assert stacktrace is None

    async def test_format_stacktrace_returns_none_for_empty_exception_list(self):
        context = self._create_context(self.issue_id_one)

        event: dict = {"properties": {"$exception_list": []}}
        stacktrace = context.format_stacktrace(event)

        assert stacktrace is None

    async def test_execute_and_format_returns_error_for_nonexistent_issue(self):
        context = self._create_context("00000000-0000-0000-0000-000000000000")
        result = await context.execute_and_format()

        assert "not found" in result

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

        assert "TypeError: Cannot read property 'map' of undefined" in result
        assert "Issue ID:" in result
        assert "Stack Trace" in result
        assert "processData" in result

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

        assert "Custom Issue Name" in result

    @patch.object(ErrorTrackingIssueContext, "aget_first_event")
    async def test_execute_and_format_returns_error_when_no_events(self, mock_get_event):
        mock_get_event.return_value = None

        context = self._create_context(self.issue_id_one)
        result = await context.execute_and_format()

        assert "No events found" in result

    @patch.object(ErrorTrackingIssueContext, "aget_first_event")
    async def test_execute_and_format_returns_error_when_no_stacktrace(self, mock_get_event):
        mock_get_event.return_value = {"properties": {"$exception_list": []}}

        context = self._create_context(self.issue_id_one)
        result = await context.execute_and_format()

        assert "No stack trace available" in result
