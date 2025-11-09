from datetime import UTC, datetime
from uuid import uuid4

from posthog.temporal.weekly_digest.types import (
    DashboardList,
    Digest,
    DigestDashboard,
    DigestEventDefinition,
    DigestExperiment,
    DigestExternalDataSource,
    DigestFeatureFlag,
    DigestFilter,
    DigestRecording,
    DigestSurvey,
    EventDefinitionList,
    ExperimentList,
    ExternalDataSourceList,
    FeatureFlagList,
    FilterList,
    OrganizationDigest,
    RecordingList,
    SurveyList,
    TeamDigest,
)


def test_digest_render_payload():
    """Test that Digest renders its payload correctly."""
    period_start = datetime(2024, 1, 1, tzinfo=UTC)
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    digest = Digest(key="weekly-digest-2024-1", period_start=period_start, period_end=period_end)

    payload = digest.render_payload()

    assert payload["digest_key"] == "weekly-digest-2024-1"
    assert payload["start_inclusive"] == "2024-01-01T00:00:00+00:00"
    assert payload["end_inclusive"] == "2024-01-08T00:00:00+00:00"


def test_digest_filter_render_payload():
    """Test that DigestFilter renders its payload correctly."""
    filter = DigestFilter(
        name="High Value Users", short_id="abc123", view_count=5, recording_count=10, more_available=True
    )

    payload = filter.render_payload()

    assert payload["name"] == "High Value Users"
    assert payload["count"] == 10
    assert payload["has_more_available"] is True
    assert payload["url_path"] == "/replay/home/?filterId=abc123"


def test_digest_filter_render_payload_untitled():
    """Test that DigestFilter renders untitled filters correctly."""
    filter = DigestFilter(name=None, short_id="def456", view_count=3, recording_count=5)

    payload = filter.render_payload()

    assert payload["name"] == "Untitled"


def test_filter_list_order_by_recording_count():
    """Test that FilterList orders filters by recording count."""
    filters = FilterList(
        root=[
            DigestFilter(name="Filter A", short_id="a", view_count=1, recording_count=5),
            DigestFilter(name="Filter B", short_id="b", view_count=2, recording_count=10),
            DigestFilter(name="Filter C", short_id="c", view_count=3, recording_count=2),
        ]
    )

    ordered = filters.order_by_recording_count()

    assert len(ordered.root) == 3
    assert ordered.root[0].short_id == "b"  # 10 recordings
    assert ordered.root[1].short_id == "a"  # 5 recordings
    assert ordered.root[2].short_id == "c"  # 2 recordings


def test_team_digest_is_empty():
    """Test that TeamDigest correctly identifies empty digests."""
    empty_digest = TeamDigest(
        id=1,
        name="Test Team",
        dashboards=DashboardList(root=[]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    assert empty_digest.is_empty() is True

    non_empty_digest = TeamDigest(
        id=1,
        name="Test Team",
        dashboards=DashboardList(root=[DigestDashboard(name="Dashboard 1", id=1)]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    assert non_empty_digest.is_empty() is False


def test_team_digest_count_nonempty():
    """Test that TeamDigest correctly counts non-empty fields."""
    digest = TeamDigest(
        id=1,
        name="Test Team",
        dashboards=DashboardList(root=[DigestDashboard(name="Dashboard 1", id=1)]),
        event_definitions=EventDefinitionList(root=[DigestEventDefinition(name="pageview", id=uuid4())]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[DigestFeatureFlag(name="Feature", id=1, key="feature")]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    assert digest.count_nonempty() == 3  # dashboards, event_definitions, feature_flags


def test_team_digest_render_payload():
    """Test that TeamDigest renders its payload correctly."""
    dashboard = DigestDashboard(name="Dashboard 1", id=1)
    event = DigestEventDefinition(name="pageview", id=uuid4())
    flag = DigestFeatureFlag(name="Feature", id=1, key="feature")
    filter = DigestFilter(name="Filter", short_id="abc", view_count=5, recording_count=10)

    digest = TeamDigest(
        id=1,
        name="Test Team",
        dashboards=DashboardList(root=[dashboard]),
        event_definitions=EventDefinitionList(root=[event]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[flag]),
        filters=FilterList(root=[filter]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    payload = digest.render_payload()

    assert payload["team_name"] == "Test Team"
    assert payload["team_id"] == 1
    assert "report" in payload
    report = payload["report"]
    assert isinstance(report, dict)
    assert len(report["new_dashboards"]) == 1
    assert len(report["new_event_definitions"]) == 1
    assert len(report["new_feature_flags"]) == 1
    assert len(report["interesting_saved_filters"]) == 1


def test_organization_digest_filter_for_user():
    """Test that OrganizationDigest correctly filters teams for a user."""
    team1 = TeamDigest(
        id=1,
        name="Team 1",
        dashboards=DashboardList(root=[DigestDashboard(name="Dashboard", id=1)]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    team2 = TeamDigest(
        id=2,
        name="Team 2",
        dashboards=DashboardList(root=[DigestDashboard(name="Dashboard 2", id=2)]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    team3 = TeamDigest(
        id=3,
        name="Team 3",
        dashboards=DashboardList(root=[DigestDashboard(name="Dashboard 3", id=3)]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    org = OrganizationDigest(
        id=uuid4(), name="Test Org", created_at=datetime.now(UTC), team_digests=[team1, team2, team3]
    )

    # User only has access to teams 1 and 3
    user_teams = {1, 3}
    filtered = org.filter_for_user(user_teams)

    assert len(filtered.team_digests) == 2
    assert filtered.team_digests[0].id == 1
    assert filtered.team_digests[1].id == 3


def test_organization_digest_is_empty():
    """Test that OrganizationDigest correctly identifies empty digests."""
    empty_team = TeamDigest(
        id=1,
        name="Empty Team",
        dashboards=DashboardList(root=[]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    org = OrganizationDigest(id=uuid4(), name="Test Org", created_at=datetime.now(UTC), team_digests=[empty_team])

    assert org.is_empty() is True

    non_empty_team = TeamDigest(
        id=2,
        name="Non-Empty Team",
        dashboards=DashboardList(root=[DigestDashboard(name="Dashboard", id=1)]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    org.team_digests.append(non_empty_team)

    assert org.is_empty() is False


def test_organization_digest_count_nonempty():
    """Test that OrganizationDigest correctly counts non-empty items across teams."""
    team1 = TeamDigest(
        id=1,
        name="Team 1",
        dashboards=DashboardList(root=[DigestDashboard(name="Dashboard", id=1)]),
        event_definitions=EventDefinitionList(root=[DigestEventDefinition(name="event", id=uuid4())]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    team2 = TeamDigest(
        id=2,
        name="Team 2",
        dashboards=DashboardList(root=[]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[DigestFeatureFlag(name="Flag", id=1, key="flag")]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    org = OrganizationDigest(id=uuid4(), name="Test Org", created_at=datetime.now(UTC), team_digests=[team1, team2])

    # Team 1 has 2 non-empty fields, Team 2 has 1
    assert org.count_nonempty() == 3


def test_organization_digest_render_payload():
    """Test that OrganizationDigest renders its payload correctly."""
    team = TeamDigest(
        id=1,
        name="Test Team",
        dashboards=DashboardList(root=[DigestDashboard(name="Dashboard", id=1)]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        recordings=RecordingList(root=[]),
        surveys_launched=SurveyList(root=[]),
    )

    org_id = uuid4()
    org = OrganizationDigest(id=org_id, name="Test Org", created_at=datetime.now(UTC), team_digests=[team])

    period_start = datetime(2024, 1, 1, tzinfo=UTC)
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    digest = Digest(key="weekly-digest-2024-1", period_start=period_start, period_end=period_end)

    payload = org.render_payload(digest)

    assert payload["organization_name"] == "Test Org"
    assert payload["organization_id"] == str(org_id)
    assert payload["scope"] == "user"
    assert payload["template_name"] == "weekly_digest_report"
    teams = payload["teams"]
    assert isinstance(teams, list)
    assert len(teams) == 1
    assert payload["nonempty_items"] == 1
    assert "period" in payload


def test_digest_experiment_with_end_date():
    """Test that DigestExperiment correctly handles experiments with end dates."""
    start_date = datetime(2024, 1, 1, tzinfo=UTC)
    end_date = datetime(2024, 1, 15, tzinfo=UTC)

    experiment = DigestExperiment(name="Test Experiment", id=1, start_date=start_date, end_date=end_date)

    assert experiment.name == "Test Experiment"
    assert experiment.id == 1
    assert experiment.start_date == start_date
    assert experiment.end_date == end_date


def test_digest_experiment_without_end_date():
    """Test that DigestExperiment correctly handles experiments without end dates."""
    start_date = datetime(2024, 1, 1, tzinfo=UTC)

    experiment = DigestExperiment(name="Ongoing Experiment", id=2, start_date=start_date)

    assert experiment.name == "Ongoing Experiment"
    assert experiment.id == 2
    assert experiment.start_date == start_date
    assert experiment.end_date is None


def test_digest_recording():
    """Test that DigestRecording correctly stores recording data."""
    recording = DigestRecording(session_id="session123", recording_ttl=7)

    assert recording.session_id == "session123"
    assert recording.recording_ttl == 7


def test_digest_survey():
    """Test that DigestSurvey correctly stores survey data."""
    start_date = datetime(2024, 1, 1, tzinfo=UTC)
    survey_id = uuid4()

    survey = DigestSurvey(
        name="Customer Survey", id=survey_id, description="How satisfied are you?", start_date=start_date
    )

    assert survey.name == "Customer Survey"
    assert survey.id == survey_id
    assert survey.description == "How satisfied are you?"
    assert survey.start_date == start_date


def test_digest_external_data_source():
    """Test that DigestExternalDataSource correctly stores data source info."""
    source_id = uuid4()
    source = DigestExternalDataSource(source_type="stripe", id=source_id)

    assert source.source_type == "stripe"
    assert source.id == source_id
