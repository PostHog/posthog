from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class TestSessionRecordingMissingReason(APIBaseTest, ClickhouseTestMixin):
    def setUp(self):
        super().setUp()
        # Ensure clean CH state
        sync_execute("TRUNCATE TABLE sharded_events")
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")

    def _create_pageview(self, session_id: str, url: str, ts: datetime | None = None) -> None:
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user_1",
            timestamp=ts or datetime.now(tz=UTC),
            properties={"$session_id": session_id, "$current_url": url},
        )

    def _create_event(self, session_id: str, event: str, ts: datetime | None = None) -> None:
        _create_event(
            event=event,
            team=self.team,
            distinct_id="user_1",
            timestamp=ts or datetime.now(tz=UTC),
            properties={"$session_id": session_id},
        )

    def test_recorded_fast_path(self) -> None:
        session_id = "recorded-session"
        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_id,
            distinct_id="user_1",
            first_timestamp=datetime.now(tz=UTC),
            last_timestamp=datetime.now(tz=UTC),
            ensure_analytics_event_in_session=False,
            retention_period_days=90,
        )
        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "recorded"

    def test_session_missing_when_no_events(self) -> None:
        session_id = "non-existent"
        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "session_missing"

    def test_replay_disabled(self) -> None:
        session_id = str(uuid7())
        self._create_pageview(session_id, "https://example.com/")
        flush_persons_and_events()
        self.team.session_recording_opt_in = False
        self.team.save()

        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "replay_disabled"

    def test_domain_not_allowed(self) -> None:
        session_id = str(uuid7())
        self._create_pageview(session_id, "https://blocked.example.org/path")
        flush_persons_and_events()
        self.team.session_recording_opt_in = True
        self.team.recording_domains = ["allowed.example.org"]
        self.team.save()

        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "domain_not_allowed"

    def test_url_blocklisted(self) -> None:
        session_id = str(uuid7())
        self._create_pageview(session_id, "https://example.com/secret")
        flush_persons_and_events()
        self.team.session_recording_opt_in = True
        self.team.session_recording_url_blocklist_config = [{"url": "secret"}]
        self.team.save()

        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "url_blocklisted"

    def test_below_min_duration(self) -> None:
        session_id = str(uuid7())
        base = datetime.now(tz=UTC)
        self._create_event(session_id, "custom", ts=base)
        self._create_event(session_id, "custom", ts=base + timedelta(seconds=1))
        flush_persons_and_events()
        self.team.session_recording_opt_in = True
        self.team.session_recording_minimum_duration_milliseconds = 5000
        self.team.save()

        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "below_min_duration"

    def test_sampled_out_best_effort(self) -> None:
        session_id = str(uuid7())
        self._create_pageview(session_id, "https://example.com/")
        flush_persons_and_events()
        self.team.session_recording_opt_in = True
        self.team.session_recording_sample_rate = "0.10"
        self.team.session_recording_minimum_duration_milliseconds = None
        self.team.session_recording_url_trigger_config = None
        self.team.session_recording_event_trigger_config = None
        self.team.save()

        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "sampled_out"

    def test_triggers_not_matched_url(self) -> None:
        session_id = str(uuid7())
        # URL does not match the trigger pattern
        self._create_pageview(session_id, "https://example.com/home")
        flush_persons_and_events()
        self.team.session_recording_opt_in = True
        self.team.session_recording_url_trigger_config = [{"url": "checkout"}]
        self.team.session_recording_trigger_match_type_config = "all"
        self.team.save()

        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "triggers_not_matched"
        assert "triggers" in resp.json()["details"]

    def test_triggers_not_matched_flag_link(self) -> None:
        session_id = str(uuid7())
        # No $feature_flag_called events emitted
        self._create_pageview(session_id, "https://example.com/")
        flush_persons_and_events()
        self.team.session_recording_opt_in = True
        self.team.session_recording_linked_flag = {"key": "rec-flag"}
        self.team.session_recording_trigger_match_type_config = "all"
        self.team.save()

        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        body = resp.json()
        assert body["reason"] == "triggers_not_matched"
        assert body["details"]["triggers"]["flag"]["key"] == "rec-flag"
        assert body["details"]["triggers"]["flag"]["matched"] is False

    def test_retention_expired(self) -> None:
        session_id = str(uuid7())
        # Team retention 30d; make session older than TTL
        self.team.session_recording_retention_period = "30d"
        self.team.session_recording_opt_in = True
        self.team.save()
        old = datetime.now(tz=UTC) - timedelta(days=40)
        with freeze_time(datetime.now(tz=UTC)):
            self._create_event(session_id, "custom", ts=old)
            self._create_event(session_id, "custom", ts=old + timedelta(seconds=5))
            flush_persons_and_events()

        resp = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/missing-reason")
        assert resp.status_code == status.HTTP_200_OK, resp.json()
        assert resp.json()["reason"] == "retention_expired"
