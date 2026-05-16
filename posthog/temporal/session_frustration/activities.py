"""Temporal activities for session frustration detection."""

from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache

import structlog
import temporalio.activity

from posthog.api.capture import capture_internal
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.session_frustration.constants import (
    DETECTION_METHOD,
    EVENT_NAME,
    EVENT_SOURCE,
    MAX_EVENTS_PER_TEAM,
    MIN_FRUSTRATION_SCORE,
    PERSON_FREQUENCY_CAP_TTL,
    REDIS_KEY_PREFIX,
    SESSION_COMPLETED_THRESHOLD_MINUTES,
    SESSION_DEDUP_TTL,
)
from posthog.temporal.session_frustration.types import FrustratedSession, TeamWorkflowInputs

logger = structlog.get_logger(__name__)


def _session_dedup_key(team_id: int, session_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}:session:{team_id}:{session_id}"


def _person_frequency_key(team_id: int, distinct_id: str) -> str:
    return f"{REDIS_KEY_PREFIX}:person:{team_id}:{distinct_id}"


@temporalio.activity.defn
async def get_opted_in_team_ids_activity() -> list[tuple[int, str]]:
    """Return (team_id, api_token) for teams with frustration detection enabled."""

    def _fetch() -> list[tuple[int, str]]:
        return list(Team.objects.filter(frustration_detection_enabled=True).values_list("id", "api_token").iterator())

    return await database_sync_to_async(_fetch)()


@temporalio.activity.defn
async def query_frustrated_sessions_activity(inputs: TeamWorkflowInputs) -> list[FrustratedSession]:
    """Query ClickHouse for sessions with high frustration signals."""

    def _query() -> list[FrustratedSession]:
        now_ts = datetime.now(UTC)
        date_from = now_ts - timedelta(hours=inputs.lookback_hours)

        tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=inputs.team_id)

        # Step 1: Find sessions with frustration signals from events table
        frustration_query = """
            SELECT
                `$session_id` AS session_id,
                any(distinct_id) AS distinct_id,
                countIf(event = '$rageclick') * 3
                    + countIf(event = '$exception') * 2
                    AS frustration_score,
                countIf(event = '$rageclick') AS rage_click_count,
                countIf(event = '$exception') AS exception_count
            FROM events
            WHERE
                team_id = %(team_id)s
                AND event IN ('$rageclick', '$exception')
                AND timestamp >= %(date_from)s
                AND timestamp <= %(date_to)s
                AND notEmpty(`$session_id`)
            GROUP BY `$session_id`
            HAVING frustration_score >= %(min_frustration_score)s
            ORDER BY frustration_score DESC
            LIMIT %(limit)s
        """

        frustration_results = sync_execute(
            frustration_query,
            {
                "team_id": inputs.team_id,
                "date_from": date_from,
                "date_to": now_ts,
                "min_frustration_score": MIN_FRUSTRATION_SCORE,
                "limit": MAX_EVENTS_PER_TEAM,
            },
        )

        if not frustration_results:
            return []

        session_ids = [row[0] for row in frustration_results]
        frustration_by_session: dict[str, tuple[str, int, int, int]] = {
            row[0]: (row[1], row[2], row[3], row[4]) for row in frustration_results
        }

        # Step 2: Enrich with session metadata, filter to completed sessions only
        metadata_query = """
            SELECT
                session_id,
                min(min_first_timestamp) AS session_start,
                dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) AS duration_seconds,
                sum(console_error_count) AS console_error_count,
                argMinMerge(first_url) AS first_url
            FROM session_replay_events
            WHERE
                team_id = %(team_id)s
                AND session_id IN %(session_ids)s
                AND max_last_timestamp < now() - INTERVAL %(completed_threshold)s MINUTE
            GROUP BY session_id
        """

        metadata_results = sync_execute(
            metadata_query,
            {
                "team_id": inputs.team_id,
                "session_ids": session_ids,
                "completed_threshold": SESSION_COMPLETED_THRESHOLD_MINUTES,
            },
        )

        metadata_by_session: dict[str, tuple[datetime, int, int, str]] = {
            row[0]: (row[1], row[2], row[3], row[4]) for row in metadata_results
        }

        sessions: list[FrustratedSession] = []
        for session_id in session_ids:
            if session_id not in metadata_by_session:
                continue  # Session still active or no replay data

            distinct_id, frustration_score, rage_click_count, exception_count = frustration_by_session[session_id]
            session_start, duration_seconds, console_error_count, first_url = metadata_by_session[session_id]

            sessions.append(
                FrustratedSession(
                    session_id=session_id,
                    distinct_id=distinct_id,
                    frustration_score=frustration_score,
                    rage_click_count=rage_click_count,
                    exception_count=exception_count,
                    console_error_count=console_error_count,
                    duration_seconds=duration_seconds,
                    first_url=first_url or "",
                    session_start=session_start,
                )
            )

        return sessions

    return await database_sync_to_async(_query, thread_sensitive=False)()


@temporalio.activity.defn
async def filter_already_emitted_activity(
    team_id: int,
    sessions: list[FrustratedSession],
) -> list[FrustratedSession]:
    """Filter out sessions that have already been emitted or persons at frequency cap."""

    def _filter() -> list[FrustratedSession]:
        new_sessions: list[FrustratedSession] = []
        for session in sessions:
            session_key = _session_dedup_key(team_id, session.session_id)
            if cache.get(session_key) is not None:
                continue

            person_key = _person_frequency_key(team_id, session.distinct_id)
            if cache.get(person_key) is not None:
                continue

            new_sessions.append(session)

        return new_sessions

    return await database_sync_to_async(_filter, thread_sensitive=False)()


@temporalio.activity.defn
async def emit_frustration_events_activity(
    team_id: int,
    api_token: str,
    sessions: list[FrustratedSession],
) -> int:
    """Emit $session_frustration_detected events via capture_internal and mark as emitted."""

    def _emit() -> int:
        emitted = 0
        for session in sessions:
            replay_url = f"{settings.SITE_URL}/project/{team_id}/replay/{session.session_id}"

            properties: dict[str, Any] = {
                "$session_id": session.session_id,
                "frustration_score": session.frustration_score,
                "rage_click_count": session.rage_click_count,
                "exception_count": session.exception_count,
                "console_error_count": session.console_error_count,
                "session_duration_seconds": session.duration_seconds,
                "session_first_url": session.first_url,
                "session_replay_url": replay_url,
                "detection_method": DETECTION_METHOD,
            }

            try:
                resp = capture_internal(
                    token=api_token,
                    event_name=EVENT_NAME,
                    event_source=EVENT_SOURCE,
                    distinct_id=session.distinct_id,
                    timestamp=datetime.now(UTC),
                    properties=properties,
                    process_person_profile=False,
                )
                resp.raise_for_status()

                # Mark as emitted in Redis
                session_key = _session_dedup_key(team_id, session.session_id)
                cache.set(session_key, 1, int(SESSION_DEDUP_TTL.total_seconds()))

                person_key = _person_frequency_key(team_id, session.distinct_id)
                cache.set(person_key, 1, int(PERSON_FREQUENCY_CAP_TTL.total_seconds()))

                emitted += 1
            except Exception:
                logger.exception(
                    "Failed to emit frustration event",
                    team_id=team_id,
                    session_id=session.session_id,
                )

        return emitted

    return await database_sync_to_async(_emit, thread_sensitive=False)()
