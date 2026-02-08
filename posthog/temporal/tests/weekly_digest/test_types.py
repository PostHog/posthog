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
    DigestProductSuggestion,
    DigestSurvey,
    EventDefinitionList,
    ExperimentList,
    ExternalDataSourceList,
    FeatureFlagList,
    FilterList,
    OrganizationDigest,
    RecordingCount,
    SurveyList,
    TeamDigest,
    UserDigestContext,
    UserSpecificDigest,
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
        expiring_recordings=RecordingCount(recording_count=0),
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    assert non_empty_digest.is_empty() is False


def test_team_digest_count_items():
    """Test that TeamDigest correctly counts items."""
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
        expiring_recordings=RecordingCount(recording_count=5),
        surveys_launched=SurveyList(root=[]),
    )

    assert digest.count_items() == 3  # dashboards, event_definitions, feature_flags


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
        expiring_recordings=RecordingCount(recording_count=7),
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
    assert "expiring_recordings" in report
    expiring_recordings = report["expiring_recordings"]
    assert isinstance(expiring_recordings, dict)
    assert expiring_recordings["recording_count"] == 7


def test_team_digest_render_payload_empty_recordings():
    """Test that TeamDigest renders its payload correctly with empty recordings."""
    dashboard = DigestDashboard(name="Dashboard 1", id=1)

    digest = TeamDigest(
        id=1,
        name="Test Team",
        dashboards=DashboardList(root=[dashboard]),
        event_definitions=EventDefinitionList(root=[]),
        experiments_launched=ExperimentList(root=[]),
        experiments_completed=ExperimentList(root=[]),
        external_data_sources=ExternalDataSourceList(root=[]),
        feature_flags=FeatureFlagList(root=[]),
        filters=FilterList(root=[]),
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    payload = digest.render_payload()

    report = payload["report"]
    assert isinstance(report, dict)
    assert "expiring_recordings" in report
    expiring_recordings = report["expiring_recordings"]
    assert isinstance(expiring_recordings, dict)
    assert expiring_recordings["recording_count"] == 0


def test_organization_digest_for_user():
    """Test that OrganizationDigest.for_user correctly filters teams and returns UserSpecificDigest."""
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
        expiring_recordings=RecordingCount(recording_count=0),
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
        expiring_recordings=RecordingCount(recording_count=0),
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    org = OrganizationDigest(
        id=uuid4(), name="Test Org", created_at=datetime.now(UTC), team_digests=[team1, team2, team3]
    )

    # User only has access to teams 1 and 3
    user_teams = {1, 3}
    user_digest = org.for_user(user_teams)

    assert isinstance(user_digest, UserSpecificDigest)
    assert len(user_digest.team_digests) == 2
    assert user_digest.team_digests[0].id == 1
    assert user_digest.team_digests[1].id == 3
    assert user_digest.context.product_suggestion is None


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
        expiring_recordings=RecordingCount(recording_count=0),
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    org.team_digests.append(non_empty_team)

    assert org.is_empty() is False


def test_organization_digest_count_items():
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
        expiring_recordings=RecordingCount(recording_count=0),
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    org = OrganizationDigest(id=uuid4(), name="Test Org", created_at=datetime.now(UTC), team_digests=[team1, team2])

    # Team 1 has 2 items, Team 2 has 1
    assert org.count_items() == 3


def test_user_specific_digest_render_payload():
    """Test that UserSpecificDigest renders its payload correctly."""
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    org_id = uuid4()
    org = OrganizationDigest(id=org_id, name="Test Org", created_at=datetime.now(UTC), team_digests=[team])
    user_digest = org.for_user({1})

    period_start = datetime(2024, 1, 1, tzinfo=UTC)
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    digest = Digest(key="weekly-digest-2024-1", period_start=period_start, period_end=period_end)

    payload = user_digest.render_payload(digest)

    assert payload["organization_name"] == "Test Org"
    assert payload["organization_id"] == str(org_id)
    assert payload["scope"] == "user"
    assert payload["template_name"] == "weekly_digest_report"
    teams = payload["teams"]
    assert isinstance(teams, list)
    assert [t["team_id"] for t in teams] == [1]
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


def test_recording_count():
    """Test that RecordingCount correctly stores recording count data."""
    recording_count = RecordingCount(recording_count=7)

    assert recording_count.recording_count == 7


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


def test_digest_product_suggestion_get_readable_reason_text_with_custom_text():
    """Test that custom reason_text takes precedence."""
    suggestion = DigestProductSuggestion(
        team_id=1,
        product_path="Error tracking",
        reason="used_by_colleagues",
        reason_text="Custom message for this user",
    )

    assert suggestion.get_readable_reason_text() == "Custom message for this user"


def test_digest_product_suggestion_get_readable_reason_text_fallback_to_default():
    """Test that reason enum maps to default text when reason_text is None."""
    suggestion = DigestProductSuggestion(
        team_id=1,
        product_path="Session replay",
        reason="sales_led",
        reason_text=None,
    )

    assert suggestion.get_readable_reason_text() == "This product is recommended for you by our team."


def test_digest_product_suggestion_get_readable_reason_text_supported_reasons():
    """Test that sales_led and new_product reasons map to readable text."""
    reason_mappings = {
        "new_product": "This is a brand new product. Give it a try!",
        "sales_led": "This product is recommended for you by our team.",
    }

    for reason, expected_text in reason_mappings.items():
        suggestion = DigestProductSuggestion(
            team_id=1,
            product_path="Test Product",
            reason=reason,
            reason_text=None,
        )
        assert suggestion.get_readable_reason_text() == expected_text, f"Failed for reason: {reason}"


def test_digest_product_suggestion_get_readable_reason_text_unsupported_reason():
    """Test that unsupported reasons return None (fallback)."""
    suggestion = DigestProductSuggestion(
        team_id=1,
        product_path="Test Product",
        reason="used_by_colleagues",  # Not in digest defaults
        reason_text=None,
    )

    assert suggestion.get_readable_reason_text() is None


def test_digest_product_suggestion_get_readable_reason_text_no_reason():
    """Test that None is returned when neither reason nor reason_text is set."""
    suggestion = DigestProductSuggestion(
        team_id=1,
        product_path="Feature flags",
        reason=None,
        reason_text=None,
    )

    assert suggestion.get_readable_reason_text() is None


def test_user_specific_digest_render_payload_with_product_suggestion():
    """Test that UserSpecificDigest renders a product suggestion in the correct team's report."""
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    org_id = uuid4()
    org = OrganizationDigest(id=org_id, name="Test Org", created_at=datetime.now(UTC), team_digests=[team])

    period_start = datetime(2024, 1, 1, tzinfo=UTC)
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    digest = Digest(key="weekly-digest-2024-1", period_start=period_start, period_end=period_end)

    suggestion = DigestProductSuggestion(
        team_id=1,
        product_path="Error tracking",
        reason="sales_led",
        reason_text=None,
    )

    user_digest = org.for_user({1}, UserDigestContext(product_suggestion=suggestion))
    payload = user_digest.render_payload(digest)

    # Suggestion should be in the team's report, not at org level
    assert "new_product_suggestion" not in payload
    teams = payload["teams"]
    assert isinstance(teams, list)
    assert len(teams) == 1
    team_report = teams[0]["report"]
    assert "new_product_suggestion" in team_report
    new_suggestion = team_report["new_product_suggestion"]
    assert new_suggestion["product_path"] == "Error tracking"
    assert new_suggestion["reason_text"] == "This product is recommended for you by our team."


def test_user_specific_digest_render_payload_with_custom_reason_text():
    """Test that custom reason_text is used when provided."""
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    org_id = uuid4()
    org = OrganizationDigest(id=org_id, name="Test Org", created_at=datetime.now(UTC), team_digests=[team])

    period_start = datetime(2024, 1, 1, tzinfo=UTC)
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    digest = Digest(key="weekly-digest-2024-1", period_start=period_start, period_end=period_end)

    suggestion = DigestProductSuggestion(
        team_id=1,
        product_path="Session replay",
        reason="product_intent",
        reason_text="Custom reason text for this user",
    )

    user_digest = org.for_user({1}, UserDigestContext(product_suggestion=suggestion))
    payload = user_digest.render_payload(digest)

    teams = payload["teams"]
    assert isinstance(teams, list)

    team_report = teams[0]["report"]
    assert isinstance(team_report, dict)

    suggestion_payload = team_report["new_product_suggestion"]
    assert isinstance(suggestion_payload, dict)
    assert suggestion_payload["reason_text"] == "Custom reason text for this user"


def test_user_specific_digest_render_payload_suggestion_wrong_team():
    """Test that suggestion doesn't appear if team_id doesn't match."""
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    org_id = uuid4()
    org = OrganizationDigest(id=org_id, name="Test Org", created_at=datetime.now(UTC), team_digests=[team])

    period_start = datetime(2024, 1, 1, tzinfo=UTC)
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    digest = Digest(key="weekly-digest-2024-1", period_start=period_start, period_end=period_end)

    # Suggestion is for team 999, but we only have team 1
    suggestion = DigestProductSuggestion(
        team_id=999,
        product_path="Error tracking",
        reason="sales_led",
        reason_text=None,
    )

    user_digest = org.for_user({1}, UserDigestContext(product_suggestion=suggestion))
    payload = user_digest.render_payload(digest)

    teams = payload["teams"]
    assert isinstance(teams, list)
    assert len(teams) == 1

    team_report = teams[0]["report"]
    assert isinstance(team_report, dict)
    assert "new_product_suggestion" not in team_report


def test_user_specific_digest_render_payload_without_product_suggestion():
    """Test that UserSpecificDigest renders correctly without product suggestion."""
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
        expiring_recordings=RecordingCount(recording_count=0),
        surveys_launched=SurveyList(root=[]),
    )

    org_id = uuid4()
    org = OrganizationDigest(id=org_id, name="Test Org", created_at=datetime.now(UTC), team_digests=[team])

    period_start = datetime(2024, 1, 1, tzinfo=UTC)
    period_end = datetime(2024, 1, 8, tzinfo=UTC)
    digest = Digest(key="weekly-digest-2024-1", period_start=period_start, period_end=period_end)

    user_digest = org.for_user({1})
    payload = user_digest.render_payload(digest)

    teams = payload["teams"]
    assert isinstance(teams, list)

    team_report = teams[0]["report"]
    assert isinstance(team_report, dict)
    assert "new_product_suggestion" not in team_report
