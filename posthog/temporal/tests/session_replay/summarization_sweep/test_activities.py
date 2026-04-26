import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.temporal.session_replay.summarization_sweep.activities import find_sessions_for_team_activity
from posthog.temporal.session_replay.summarization_sweep.models import FindSessionsInput

from products.signals.backend.models import SignalSourceConfig

from .conftest import enable_signal_source


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_returns_team_disabled_when_no_config(activity_environment, team):
    """No config row at all → treat as disabled so the workflow tears down its schedule."""
    result = await activity_environment.run(
        find_sessions_for_team_activity,
        FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=5),
    )
    assert result.team_disabled is True
    assert result.session_ids == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_returns_team_disabled_when_config_disabled(activity_environment, team):
    await sync_to_async(enable_signal_source)(team, enabled=False)
    result = await activity_environment.run(
        find_sessions_for_team_activity,
        FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=5),
    )
    assert result.team_disabled is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_no_recent_sessions(activity_environment, team):
    await sync_to_async(enable_signal_source)(team)
    with patch(
        "posthog.temporal.session_replay.summarization_sweep.activities.fetch_recent_session_ids",
        return_value=[],
    ):
        result = await activity_environment.run(
            find_sessions_for_team_activity,
            FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=5),
        )
    assert result.team_disabled is False
    assert result.team_id == team.id
    assert result.session_ids == []
    assert result.user_id is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_filters_summarized(activity_environment, organization, team):
    from posthog.models.user import User

    await sync_to_async(enable_signal_source)(team)
    user = await sync_to_async(User.objects.create_and_join)(organization, "sweep-user@posthog.com", "pw", "Sweep")
    try:
        raw_ids = ["s1", "s2", "s3"]
        existing = {"s1": True, "s2": False, "s3": True}
        with (
            patch(
                "posthog.temporal.session_replay.summarization_sweep.activities.fetch_recent_session_ids",
                return_value=raw_ids,
            ),
            patch(
                "ee.models.session_summaries.SingleSessionSummary.objects.summaries_exist",
                return_value=existing,
            ),
        ):
            result = await activity_environment.run(
                find_sessions_for_team_activity,
                FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=5),
            )
        assert result.session_ids == ["s2"]
        assert result.user_id == user.id
        assert result.user_distinct_id == user.distinct_id
    finally:
        await sync_to_async(user.delete)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_applies_max_sessions_after_dedup(activity_environment, organization, team):
    """Older unsummarized sessions must survive when the newest ones are already summarized."""
    from posthog.models.user import User

    await sync_to_async(enable_signal_source)(team)
    user = await sync_to_async(User.objects.create_and_join)(organization, "sweep-user2@posthog.com", "pw", "Sweep")
    try:
        raw_ids = [f"s{i}" for i in range(8)]
        # First three (newest) already summarized; cap is 3 → would starve s3-s5 without post-dedup slice.
        existing = {sid: (i < 3) for i, sid in enumerate(raw_ids)}
        with (
            patch(
                "posthog.temporal.session_replay.summarization_sweep.activities.fetch_recent_session_ids",
                return_value=raw_ids,
            ),
            patch(
                "ee.models.session_summaries.SingleSessionSummary.objects.summaries_exist",
                return_value=existing,
            ),
        ):
            result = await activity_environment.run(
                find_sessions_for_team_activity,
                FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=3),
            )
        assert result.session_ids == ["s3", "s4", "s5"]
    finally:
        await sync_to_async(user.delete)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_returns_empty_when_team_has_no_user(activity_environment):
    """A team with no member users can't run summarization — we treat that as no-op, not an error."""
    lonely_org = await sync_to_async(Organization.objects.create)(name="lonely-org")
    lonely_team = await sync_to_async(Team.objects.create)(organization=lonely_org, name="lonely")
    await sync_to_async(enable_signal_source)(lonely_team)
    try:
        with patch(
            "posthog.temporal.session_replay.summarization_sweep.activities.fetch_recent_session_ids",
            return_value=["s1"],
        ):
            result = await activity_environment.run(
                find_sessions_for_team_activity,
                FindSessionsInput(team_id=lonely_team.id, lookback_minutes=30, max_sessions=5),
            )
        assert result.session_ids == []
        assert result.user_id is None
    finally:
        await sync_to_async(lonely_team.delete)()
        await sync_to_async(lonely_org.delete)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_fetch_recent_session_ids_returns_empty_when_no_config(team):
    # No SignalSourceConfig created for this team → the helper should take the
    # `_SourceNotEnabled` path and return an empty list rather than raising.
    from posthog.temporal.session_replay.summarization_sweep.session_candidates import fetch_recent_session_ids

    session_ids = await sync_to_async(fetch_recent_session_ids)(team=team, lookback_minutes=30)
    assert session_ids == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_handles_config_disabled_between_check_and_ch_query(activity_environment, team):
    """Race: _is_team_enabled returns True, then the config is disabled before
    _load_team_user_and_sessions hits ClickHouse. The helper should return an
    empty-ish `FindSessionsResult` (not team_disabled=True), which the workflow
    treats as a no-op cycle rather than firing the self-delete path.
    """
    # Pass the enabled check, then race: flip the config to disabled just as the
    # CH-bound helper starts. `fetch_recent_session_ids` re-reads the config and
    # should raise `_SourceNotEnabled` → return [] → find activity returns an
    # empty session_ids list.
    await sync_to_async(enable_signal_source)(team, enabled=True)

    def _disable_config() -> None:
        SignalSourceConfig.objects.filter(
            team_id=team.id,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        ).update(enabled=False)

    def _fake_load(team_id, lookback_minutes):
        # Runs inside the helper right after the enabled check passed — flip
        # the config mid-cycle and let the real `fetch_recent_session_ids`
        # observe a disabled config.
        from posthog.temporal.session_replay.summarization_sweep.session_candidates import fetch_recent_session_ids

        _disable_config()
        t = Team.objects.get(id=team_id)
        return t, fetch_recent_session_ids(team=t, lookback_minutes=lookback_minutes), None

    with patch(
        "posthog.temporal.session_replay.summarization_sweep.activities._load_team_user_and_sessions",
        side_effect=_fake_load,
    ):
        result = await activity_environment.run(
            find_sessions_for_team_activity,
            FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=5),
        )

    assert result.team_disabled is False
    assert result.session_ids == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_returns_team_disabled_when_ai_consent_revoked(activity_environment, team):
    await sync_to_async(enable_signal_source)(team, enabled=True)

    def _revoke() -> None:
        team.organization.is_ai_data_processing_approved = False
        team.organization.save(update_fields=["is_ai_data_processing_approved"])

    await sync_to_async(_revoke)()
    result = await activity_environment.run(
        find_sessions_for_team_activity,
        FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=5),
    )
    assert result.team_disabled is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_prefers_created_by_user(activity_environment, organization, team):
    from posthog.models.user import User

    first_user = await sync_to_async(User.objects.create_and_join)(organization, "first@posthog.com", "pw", "First")
    second_user = await sync_to_async(User.objects.create_and_join)(organization, "second@posthog.com", "pw", "Second")
    try:
        await sync_to_async(enable_signal_source)(team, created_by=second_user)
        assert first_user.id < second_user.id

        with (
            patch(
                "posthog.temporal.session_replay.summarization_sweep.activities.fetch_recent_session_ids",
                return_value=["s1"],
            ),
            patch(
                "ee.models.session_summaries.SingleSessionSummary.objects.summaries_exist",
                return_value={"s1": False},
            ),
        ):
            result = await activity_environment.run(
                find_sessions_for_team_activity,
                FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=5),
            )
        assert result.user_id == second_user.id
    finally:
        await sync_to_async(first_user.delete)()
        await sync_to_async(second_user.delete)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_falls_back_when_created_by_is_null(activity_environment, organization, team):
    from posthog.models.user import User

    await sync_to_async(enable_signal_source)(team)
    user = await sync_to_async(User.objects.create_and_join)(organization, "fallback@posthog.com", "pw", "Fallback")
    try:
        with (
            patch(
                "posthog.temporal.session_replay.summarization_sweep.activities.fetch_recent_session_ids",
                return_value=["s1"],
            ),
            patch(
                "ee.models.session_summaries.SingleSessionSummary.objects.summaries_exist",
                return_value={"s1": False},
            ),
        ):
            result = await activity_environment.run(
                find_sessions_for_team_activity,
                FindSessionsInput(team_id=team.id, lookback_minutes=30, max_sessions=5),
            )
        assert result.user_id == user.id
    finally:
        await sync_to_async(user.delete)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_enabled_teams_filters_ai_consent(activity_environment, organization):
    from posthog.temporal.session_replay.summarization_sweep.activities import list_enabled_teams_activity

    t_consented = await sync_to_async(Team.objects.create)(organization=organization, name="consented")
    await sync_to_async(enable_signal_source)(t_consented, enabled=True)

    revoked_org = await sync_to_async(Organization.objects.create)(name="revoked-org")
    t_revoked = await sync_to_async(Team.objects.create)(organization=revoked_org, name="revoked")
    await sync_to_async(enable_signal_source)(t_revoked, enabled=True)

    def _revoke() -> None:
        revoked_org.is_ai_data_processing_approved = False
        revoked_org.save(update_fields=["is_ai_data_processing_approved"])

    await sync_to_async(_revoke)()

    result = await activity_environment.run(list_enabled_teams_activity)
    assert t_consented.id in result
    assert t_revoked.id not in result
