from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from posthog.schema import ErrorTrackingIssueStatus

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
    SessionRecordingPlaylistViewed,
)
from posthog.temporal.weekly_digest.queries import query_new_error_issues, query_saved_filters, query_teams_for_digest

from products.error_tracking.backend.facade.testing import create_issue

pytestmark = pytest.mark.django_db


def _create_issue(
    team, name: str, created_at: datetime, status: ErrorTrackingIssueStatus = ErrorTrackingIssueStatus.ACTIVE
) -> UUID:
    return create_issue(team_id=team.id, name=name, status=status, created_at=created_at)


def test_query_new_error_issues_window_boundaries_and_status(team):
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    period_start = period_end - timedelta(days=7)

    in_window = _create_issue(team, "in window", period_start + timedelta(days=1))
    at_period_end = _create_issue(team, "at period end", period_end)
    _create_issue(team, "at period start", period_start)  # excluded: window is exclusive at the start
    _create_issue(team, "before window", period_start - timedelta(seconds=1))
    _create_issue(team, "after window", period_end + timedelta(seconds=1))
    for status in (
        ErrorTrackingIssueStatus.ARCHIVED,
        ErrorTrackingIssueStatus.RESOLVED,
        ErrorTrackingIssueStatus.SUPPRESSED,
        ErrorTrackingIssueStatus.PENDING_RELEASE,
    ):
        _create_issue(team, f"{status} in window", period_start + timedelta(days=1), status=status)

    results = list(query_new_error_issues(period_start, period_end))

    # Only active issues created within the window, newest first
    assert [r["id"] for r in results] == [at_period_end, in_window]
    assert all(r["team_id"] == team.id for r in results)


@pytest.mark.parametrize("with_organization", [False, True])
def test_query_teams_for_digest_loads_the_used_fields_in_one_query(
    organization, with_organization, django_assert_num_queries
):
    internal_organization = Organization.objects.create(name="internal metrics", for_internal_metrics=True)
    Team.objects.create(organization=internal_organization, name="internal metrics team")
    Team.objects.create(organization=organization, name="demo team", is_demo=True)
    digest_teams = [Team.objects.create(organization=organization, name=f"digest team {i}") for i in range(3)]

    paged_ids = []
    with django_assert_num_queries(1):
        for team in query_teams_for_digest(with_organization=with_organization):
            # Every team field the digest activities read. One left out of the query would load
            # lazily here instead, costing an extra query per team.
            _ = team.project_id, team.organization_id
            if with_organization:
                team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL)
            paged_ids.append(team.id)

    assert paged_ids == [team.id for team in digest_teams]


def test_query_saved_filters_counts_only_views_in_the_period(team, user):
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    period_start = period_end - timedelta(days=7)
    busy = SessionRecordingPlaylist.objects.create(team=team, name="Busy filter", type="filters")
    old = SessionRecordingPlaylist.objects.create(team=team, name="Old filter", type="filters")
    unviewed = SessionRecordingPlaylist.objects.create(team=team, name="Unviewed filter", type="filters")

    def view(playlist: SessionRecordingPlaylist, viewed_at: datetime) -> None:
        viewed = SessionRecordingPlaylistViewed.objects.create(team=team, user=user, playlist=playlist)
        # viewed_at is auto_now_add, so an update is the only way to backdate it.
        SessionRecordingPlaylistViewed.objects.filter(pk=viewed.pk).update(viewed_at=viewed_at)

    view(busy, period_start + timedelta(days=1))
    view(busy, period_end)
    view(busy, period_start)  # excluded: window is exclusive at the start
    view(old, period_start - timedelta(days=30))
    view(old, period_start + timedelta(days=2))
    view(old, period_end + timedelta(seconds=1))

    results = list(query_saved_filters(period_start, period_end))

    assert [(r["short_id"], r["view_count"]) for r in results] == [
        (busy.short_id, 2),
        (old.short_id, 1),
        (unviewed.short_id, 0),
    ]
