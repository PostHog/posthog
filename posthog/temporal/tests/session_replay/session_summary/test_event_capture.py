import pytest
from unittest.mock import MagicMock

from pytest_mock import MockerFixture
from requests import HTTPError, Response

from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.activities.video_based.a6c_store_video_session_summary import (
    store_video_session_summary_activity,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    SessionSentiment,
    VideoSegmentOutcome,
    VideoSessionOutcome,
    VideoSummarySingleSessionInputs,
)

from ee.models.session_summaries import ExtraSummaryContext, SessionSummaryRunMeta, SingleSessionSummary

pytestmark = pytest.mark.django_db


def test_capture_session_summary_ready_emits_internal_project_event(
    mocker: MockerFixture,
    team,
    user,
    mock_session_summary_serializer,
    settings,
):
    summary = SingleSessionSummary.objects.add_summary(
        team_id=team.id,
        session_id="summary-session-1",
        summary=mock_session_summary_serializer,
        exception_event_ids=[],
        extra_summary_context=ExtraSummaryContext(focus_area="checkout"),
        run_metadata=SessionSummaryRunMeta(model_used="gpt-test", visual_confirmation=False),
        distinct_id="customer-123",
        created_by=user,
    )
    settings.SITE_URL = "http://localhost:8000"
    response = mocker.MagicMock()
    capture_internal = mocker.patch(
        "posthog.temporal.session_replay.session_summary.event_capture.capture_internal", return_value=response
    )

    from posthog.temporal.session_replay.session_summary.event_capture import capture_session_summary_ready

    capture_session_summary_ready(summary, team_api_token="token-override")

    capture_internal.assert_called_once()
    _, kwargs = capture_internal.call_args
    assert kwargs["token"] == "token-override"
    assert kwargs["event_name"] == "$session_summary_ready"
    assert kwargs["event_source"] == "session_summary_events"
    assert kwargs["distinct_id"] == "customer-123"
    assert kwargs["properties"]["$insert_id"] == str(summary.id)
    assert kwargs["properties"]["session_id"] == "summary-session-1"
    assert kwargs["properties"]["team_id"] == team.id
    assert kwargs["properties"]["summary_id"] == str(summary.id)
    assert kwargs["properties"]["session_summary"] == summary.summary
    assert kwargs["properties"]["replay_url"] == f"http://localhost:8000/project/{team.id}/replay/summary-session-1"
    assert kwargs["properties"]["extra_summary_context"] == {"focus_area": "checkout"}
    assert kwargs["properties"]["session_summary_focus_area"] == "checkout"
    assert kwargs["properties"]["model_used"] == "gpt-test"
    assert kwargs["properties"]["session_start_time"] is None
    assert kwargs["properties"]["session_duration"] is None
    response.raise_for_status.assert_called_once()


def test_capture_session_summary_ready_swallow_capture_errors(
    mocker: MockerFixture,
    team,
    user,
    mock_session_summary_serializer,
):
    summary = SingleSessionSummary.objects.add_summary(
        team_id=team.id,
        session_id="summary-session-2",
        summary=mock_session_summary_serializer,
        exception_event_ids=[],
        distinct_id="customer-456",
        created_by=user,
    )
    response = mocker.MagicMock()
    response.raise_for_status.side_effect = HTTPError("boom", response=Response())
    mocker.patch(
        "posthog.temporal.session_replay.session_summary.event_capture.capture_internal", return_value=response
    )
    logger = mocker.patch("posthog.temporal.session_replay.session_summary.event_capture.logger")

    from posthog.temporal.session_replay.session_summary.event_capture import capture_session_summary_ready

    capture_session_summary_ready(summary, team_api_token=team.api_token)

    logger.exception.assert_called_once()


@pytest.mark.asyncio
async def test_store_video_session_summary_activity_emits_summary_ready_event(
    mocker: MockerFixture,
    ateam,
    auser,
    mock_session_summary_serializer,
):
    llm_input = MagicMock()
    llm_input.session_start_time_str = "2025-03-31T18:40:32.302000Z"
    llm_input.session_duration = 5323
    llm_input.distinct_id = "video-customer-123"

    mocker.patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a6c_store_video_session_summary.get_redis_state_client",
        return_value=(None, "input-key", None),
    )
    mocker.patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a6c_store_video_session_summary.get_data_class_from_redis",
        return_value=llm_input,
    )
    mocker.patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a6c_store_video_session_summary._convert_video_segments_to_session_summary",
        return_value=mock_session_summary_serializer.data,
    )

    capture_session_summary_ready = mocker.patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a6c_store_video_session_summary.capture_session_summary_ready"
    )

    inputs = VideoSummarySingleSessionInputs(
        session_id="video-session-1",
        user_id=auser.id,
        user_distinct_id_to_log=auser.distinct_id,
        team_id=ateam.id,
        redis_key_base="session-summary:single:1-1:video-session-1",
        model_to_use="gpt-test",
    )
    analysis = ConsolidatedVideoAnalysis(
        segments=[
            ConsolidatedVideoSegment(
                title="Checkout flow",
                start_time="00:01",
                end_time="00:20",
                description="User struggled in checkout",
                success=False,
                confusion_detected=True,
            )
        ],
        session_outcome=VideoSessionOutcome(success=False, description="User got blocked in checkout"),
        segment_outcomes=[VideoSegmentOutcome(segment_index=0, success=False, summary="User struggled")],
        sentiment=SessionSentiment(frustration_score=0.8, outcome="blocked", sentiment_signals=[]),
    )

    await store_video_session_summary_activity(inputs, analysis, ateam.api_token)

    capture_session_summary_ready.assert_called_once()
    emitted_summary = capture_session_summary_ready.call_args.args[0]
    assert emitted_summary.session_id == "video-session-1"
    assert emitted_summary.team_id == ateam.id
    assert capture_session_summary_ready.call_args.kwargs["team_api_token"] == ateam.api_token
    assert emitted_summary.run_metadata["visual_confirmation"] is True
    assert emitted_summary.run_metadata["model_used"] == "gpt-test"
    assert emitted_summary.distinct_id == "video-customer-123"
    assert emitted_summary.session_duration == 5323


@pytest.mark.asyncio
async def test_store_video_session_summary_activity_does_not_emit_existing_summary_ready_event(
    mocker: MockerFixture,
    ateam,
    auser,
    mock_session_summary_serializer,
):
    await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
        team_id=ateam.id,
        session_id="video-session-existing",
        summary=mock_session_summary_serializer,
        exception_event_ids=[],
        run_metadata=SessionSummaryRunMeta(model_used="gpt-test", visual_confirmation=True),
        distinct_id="video-customer-123",
        created_by=auser,
    )

    capture_session_summary_ready = mocker.patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a6c_store_video_session_summary.capture_session_summary_ready"
    )
    get_data_class_from_redis = mocker.patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a6c_store_video_session_summary.get_data_class_from_redis"
    )
    logger = mocker.patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a6c_store_video_session_summary.logger"
    )

    inputs = VideoSummarySingleSessionInputs(
        session_id="video-session-existing",
        user_id=auser.id,
        user_distinct_id_to_log=auser.distinct_id,
        team_id=ateam.id,
        redis_key_base="session-summary:single:1-1:video-session-existing",
        model_to_use="gpt-test",
    )
    analysis = ConsolidatedVideoAnalysis(
        segments=[],
        session_outcome=VideoSessionOutcome(success=False, description="User got blocked in checkout"),
        segment_outcomes=[],
        sentiment=SessionSentiment(frustration_score=0.8, outcome="blocked", sentiment_signals=[]),
    )

    await store_video_session_summary_activity(inputs, analysis, ateam.api_token)

    capture_session_summary_ready.assert_not_called()
    get_data_class_from_redis.assert_not_called()
    logger.warning.assert_called_once()
    logger.exception.assert_not_called()
