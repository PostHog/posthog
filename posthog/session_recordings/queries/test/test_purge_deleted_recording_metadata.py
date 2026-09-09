from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.temporal.session_replay.delete_recordings.activities import (
    delete_team_metadata_query,
    purge_delete_sessions_query,
    purge_select_markers_query,
)

# Waits for the lightweight DELETE, so the assertions read post-delete state.
DELETE_SETTINGS = {"lightweight_deletes_sync": 2, "mutations_sync": 2}


def _stored_row_count(team_id: int, session_id: str) -> int:
    [[count]] = sync_execute(
        "SELECT count() FROM session_replay_events WHERE team_id = %(team_id)s AND session_id = %(session_id)s",
        {"team_id": team_id, "session_id": session_id},
    )
    return count


class TestPurgeDeletedRecordingMetadata(ClickhouseTestMixin, BaseTest):
    def test_purge_removes_all_rows_of_an_old_shredded_recording(self):
        # The recording's rows sit in a two-month-old partition. The shred marker carries
        # the deletion time, so it sits in the current partition and never merges with
        # them. The purge must delete the recording's rows anyway, not only the marker.
        now = datetime.now(UTC)
        old_start = now - timedelta(days=60)

        produce_replay_summary(
            team_id=self.team.pk,
            session_id="shredded-session",
            first_timestamp=old_start,
            last_timestamp=old_start + timedelta(minutes=5),
            ensure_analytics_event_in_session=False,
        )
        # The deletion marker, as recording-api writes it: empty distinct_id,
        # timestamps at deletion time, past the purge grace period.
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="shredded-session",
            distinct_id="",
            first_timestamp=now - timedelta(minutes=1),
            last_timestamp=now - timedelta(minutes=1),
            is_deleted=True,
            kafka_timestamp=now - timedelta(days=11),
            ensure_analytics_event_in_session=False,
        )
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="kept-session",
            first_timestamp=old_start,
            last_timestamp=old_start + timedelta(minutes=5),
            ensure_analytics_event_in_session=False,
        )

        pairs = sync_execute(purge_select_markers_query(), {"grace_period_days": 10, "limit": 100})
        assert (self.team.pk, "shredded-session") in pairs
        assert (self.team.pk, "kept-session") not in pairs

        for team_id, session_id in pairs:
            sync_execute(
                purge_delete_sessions_query(),
                {"team_id": team_id, "session_ids": [session_id]},
                settings=DELETE_SETTINGS,
            )

        assert _stored_row_count(self.team.pk, "shredded-session") == 0
        assert _stored_row_count(self.team.pk, "kept-session") > 0

    def test_team_metadata_sweep_removes_only_that_teams_rows(self):
        now = datetime.now(UTC)
        other_team_id = self.team.pk + 1_000_000

        produce_replay_summary(
            team_id=self.team.pk,
            session_id="doomed-session",
            first_timestamp=now - timedelta(days=60),
            ensure_analytics_event_in_session=False,
        )
        produce_replay_summary(
            team_id=other_team_id,
            session_id="other-team-session",
            first_timestamp=now - timedelta(days=60),
            ensure_analytics_event_in_session=False,
        )

        sync_execute(delete_team_metadata_query(), {"team_id": self.team.pk}, settings=DELETE_SETTINGS)

        assert _stored_row_count(self.team.pk, "doomed-session") == 0
        assert _stored_row_count(other_team_id, "other-team-session") > 0
