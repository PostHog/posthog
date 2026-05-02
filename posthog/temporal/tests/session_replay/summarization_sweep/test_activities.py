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
        FindSessionsInput(team_id=team.id, lookback_minutes=30),
    )
    assert result.team_disabled is True
    assert result.session_ids == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_returns_team_disabled_when_config_disabled(activity_environment, team):
    await sync_to_async(enable_signal_source)(team, enabled=False)
    result = await activity_environment.run(
        find_sessions_for_team_activity,
        FindSessionsInput(team_id=team.id, lookback_minutes=30),
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
            FindSessionsInput(team_id=team.id, lookback_minutes=30),
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
                FindSessionsInput(team_id=team.id, lookback_minutes=30),
            )
        assert result.session_ids == ["s2"]
        assert result.user_id == user.id
        assert result.user_distinct_id == user.distinct_id
    finally:
        await sync_to_async(user.delete)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_dispatches_all_unsummarized_candidates(activity_environment, organization, team):
    """Sampling replaces the per-tick cap — every unsummarized candidate is dispatched."""
    from posthog.models.user import User

    await sync_to_async(enable_signal_source)(team)
    user = await sync_to_async(User.objects.create_and_join)(organization, "sweep-user2@posthog.com", "pw", "Sweep")
    try:
        raw_ids = [f"s{i}" for i in range(8)]
        # Newest three already summarized — the rest must survive.
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
                FindSessionsInput(team_id=team.id, lookback_minutes=30),
            )
        assert result.session_ids == ["s3", "s4", "s5", "s6", "s7"]
    finally:
        await sync_to_async(user.delete)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_passes_sample_rate_to_fetch(activity_environment, organization, team):
    """`sample_rate` from `SignalSourceConfig.config` is forwarded to `fetch_recent_session_ids`."""
    from posthog.models.user import User

    await sync_to_async(enable_signal_source)(team)
    user = await sync_to_async(User.objects.create_and_join)(organization, "sample@posthog.com", "pw", "Sample")
    await sync_to_async(SignalSourceConfig.objects.filter(team=team).update)(config={"sample_rate": 0.25})
    try:
        captured: dict[str, float] = {}

        def _fake_fetch(*, team, lookback_minutes, sample_rate, recording_filters, max_execution_time_seconds):
            captured["sample_rate"] = sample_rate
            return ["only-1"]

        with (
            patch(
                "posthog.temporal.session_replay.summarization_sweep.activities.fetch_recent_session_ids",
                side_effect=_fake_fetch,
            ),
            patch(
                "ee.models.session_summaries.SingleSessionSummary.objects.summaries_exist",
                return_value={"only-1": False},
            ),
        ):
            result = await activity_environment.run(
                find_sessions_for_team_activity,
                FindSessionsInput(team_id=team.id, lookback_minutes=30),
            )
        assert captured["sample_rate"] == 0.25
        assert result.session_ids == ["only-1"]
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
                FindSessionsInput(team_id=lonely_team.id, lookback_minutes=30),
            )
        assert result.session_ids == []
        assert result.user_id is None
    finally:
        await sync_to_async(lonely_team.delete)()
        await sync_to_async(lonely_org.delete)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_handles_config_disabled_between_check_and_ch_query(activity_environment, team):
    """Race: _is_team_enabled returns True, then the config is disabled by the time
    _load_team_user_and_sessions reads it. The single config read inside the helper
    filters by enabled=True, so it returns no row → empty session_ids → no-op cycle
    (not team_disabled=True; we don't tear down the schedule for a transient race).
    """
    await sync_to_async(enable_signal_source)(team, enabled=False)
    team.organization.is_ai_data_processing_approved = True
    await sync_to_async(team.organization.save)(update_fields=["is_ai_data_processing_approved"])

    # Force `_is_team_summarization_allowed` to True even though the config is disabled,
    # simulating the disable having happened between the check and the CH query.
    with patch(
        "posthog.temporal.session_replay.summarization_sweep.activities._is_team_summarization_allowed",
        return_value=True,
    ):
        result = await activity_environment.run(
            find_sessions_for_team_activity,
            FindSessionsInput(team_id=team.id, lookback_minutes=30),
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
        FindSessionsInput(team_id=team.id, lookback_minutes=30),
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
                FindSessionsInput(team_id=team.id, lookback_minutes=30),
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
                FindSessionsInput(team_id=team.id, lookback_minutes=30),
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_find_sessions_skips_recordings_with_too_many_failures(activity_environment, organization, team):
    from posthog.models.user import User

    await sync_to_async(enable_signal_source)(team)
    user = await sync_to_async(User.objects.create_and_join)(organization, "skip@posthog.com", "pw", "Skip")
    try:
        candidate_ids = ["good-1", "stuck-2", "good-3"]
        with (
            patch(
                "posthog.temporal.session_replay.summarization_sweep.activities.fetch_recent_session_ids",
                return_value=candidate_ids,
            ),
            patch(
                "ee.models.session_summaries.SingleSessionSummary.objects.summaries_exist",
                return_value={},
            ),
            patch(
                "posthog.temporal.session_replay.summarization_sweep.activities._stuck_session_ids",
                return_value={"stuck-2"},
            ),
        ):
            result = await activity_environment.run(
                find_sessions_for_team_activity,
                FindSessionsInput(team_id=team.id, lookback_minutes=30),
            )
        assert sorted(result.session_ids) == ["good-1", "good-3"]
    finally:
        await sync_to_async(user.delete)()


def _make_workflow_with_session(session_id: str):
    from unittest.mock import MagicMock

    attr_key = MagicMock()
    attr_key.name = "PostHogSessionRecordingId"
    pair = MagicMock()
    pair.key = attr_key
    pair.value = session_id
    wf = MagicMock()
    wf.typed_search_attributes = [pair]
    return wf


class _AsyncIter:
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_stuck_session_ids_returns_empty_for_empty_input():
    from posthog.temporal.session_replay.summarization_sweep.activities import _stuck_session_ids

    result = await _stuck_session_ids(team_id=42, session_ids=[])
    assert result == set()


@pytest.mark.asyncio
async def test_stuck_session_ids_thresholds_failures():
    from unittest.mock import AsyncMock, MagicMock

    from posthog.temporal.session_replay.summarization_sweep.activities import _stuck_session_ids
    from posthog.temporal.session_replay.summarization_sweep.constants import STUCK_RASTERIZE_THRESHOLD

    # Three failures for "stuck", one for "transient", none for "fresh".
    # The query also returns "other-recording" which isn't a candidate — must be ignored.
    workflows = (
        [_make_workflow_with_session("stuck")] * STUCK_RASTERIZE_THRESHOLD
        + [_make_workflow_with_session("transient")]
        + [_make_workflow_with_session("other-recording")] * STUCK_RASTERIZE_THRESHOLD
    )
    client = MagicMock()
    client.list_workflows = MagicMock(return_value=_AsyncIter(workflows))
    with patch(
        "posthog.temporal.session_replay.summarization_sweep.activities.async_connect",
        AsyncMock(return_value=client),
    ):
        result = await _stuck_session_ids(team_id=42, session_ids=["stuck", "transient", "fresh"])
    assert result == {"stuck"}


@pytest.mark.asyncio
async def test_stuck_session_ids_filters_by_team_and_close_time():
    """The visibility query must scope to the calling team and a bounded `CloseTime` window."""
    from freezegun import freeze_time
    from unittest.mock import AsyncMock, MagicMock

    from posthog.temporal.session_replay.summarization_sweep.activities import _stuck_session_ids
    from posthog.temporal.session_replay.summarization_sweep.constants import STUCK_RASTERIZE_LOOKBACK

    client = MagicMock()
    captured: list[str] = []

    def _list_workflows(query: str):
        captured.append(query)
        return _AsyncIter([])

    client.list_workflows = _list_workflows
    frozen = "2026-05-02T12:00:00"
    expected_cutoff = '"2026-05-02T10:00:00.000Z"'  # frozen - STUCK_RASTERIZE_LOOKBACK
    assert STUCK_RASTERIZE_LOOKBACK.total_seconds() == 2 * 3600  # guard against constant drift
    with (
        freeze_time(frozen),
        patch(
            "posthog.temporal.session_replay.summarization_sweep.activities.async_connect",
            AsyncMock(return_value=client),
        ),
    ):
        await _stuck_session_ids(team_id=4242, session_ids=["s1", "s2"])
    assert len(captured) == 1
    q = captured[0]
    assert 'WorkflowType = "rasterize-recording"' in q
    assert 'ExecutionStatus IN ("Failed", "TimedOut")' in q
    assert "PostHogTeamId = 4242" in q
    assert f"CloseTime > {expected_cutoff}" in q
    # No candidate IDs are interpolated — that's the whole point of the inversion.
    assert "s1" not in q
    assert "s2" not in q


@pytest.mark.asyncio
async def test_stuck_session_ids_swallows_temporal_errors():
    from unittest.mock import AsyncMock

    from posthog.temporal.session_replay.summarization_sweep.activities import _stuck_session_ids

    with patch(
        "posthog.temporal.session_replay.summarization_sweep.activities.async_connect",
        AsyncMock(side_effect=RuntimeError("temporal unavailable")),
    ):
        result = await _stuck_session_ids(team_id=1, session_ids=["a", "b"])
    # Degrade gracefully — better to dispatch and risk a retry than block summarization.
    assert result == set()
