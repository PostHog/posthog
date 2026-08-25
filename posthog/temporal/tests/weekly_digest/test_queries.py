from datetime import UTC, datetime, timedelta

import pytest

from posthog.temporal.weekly_digest.queries import query_new_error_issues

from products.error_tracking.backend.models import ErrorTrackingIssue

pytestmark = pytest.mark.django_db


def _create_issue(
    team,
    name: str,
    created_at: datetime,
    status: ErrorTrackingIssue.Status = ErrorTrackingIssue.Status.ACTIVE,
) -> ErrorTrackingIssue:
    issue = ErrorTrackingIssue.objects.create(team=team, name=name, status=status)
    # created_at is auto_now_add, so it has to be set after creation
    ErrorTrackingIssue.objects.filter(id=issue.id).update(created_at=created_at)
    return issue


def test_query_new_error_issues_window_boundaries_and_status(team):
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    period_start = period_end - timedelta(days=7)

    in_window = _create_issue(team, "in window", period_start + timedelta(days=1))
    at_period_end = _create_issue(team, "at period end", period_end)
    _create_issue(team, "at period start", period_start)  # excluded: window is exclusive at the start
    _create_issue(team, "before window", period_start - timedelta(seconds=1))
    _create_issue(team, "after window", period_end + timedelta(seconds=1))
    for status in (
        ErrorTrackingIssue.Status.ARCHIVED,
        ErrorTrackingIssue.Status.RESOLVED,
        ErrorTrackingIssue.Status.SUPPRESSED,
        ErrorTrackingIssue.Status.PENDING_RELEASE,
    ):
        _create_issue(team, f"{status} in window", period_start + timedelta(days=1), status=status)

    results = list(query_new_error_issues(period_start, period_end))

    # Only active issues created within the window, newest first
    assert [r["id"] for r in results] == [at_period_end.id, in_window.id]
    assert all(r["team_id"] == team.id for r in results)
