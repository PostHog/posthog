from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.integration import Integration

from products.customer_analytics.backend.logic import calendar_sync
from products.customer_analytics.backend.models import Account, Meeting, MeetingParticipant, MeetingStatus
from products.customer_analytics.backend.temporal import calendar_sync as temporal_calendar_sync


def _event(**overrides) -> dict:
    event = {
        "iCalUID": "uid-1@google.com",
        "status": "confirmed",
        "summary": "Quarterly review",
        "start": {"dateTime": "2026-08-04T15:00:00+00:00"},
        "end": {"dateTime": "2026-08-04T16:00:00+00:00"},
        "organizer": {"email": "csm@posthog.com"},
        "attendees": [
            {"email": "csm@posthog.com", "responseStatus": "accepted"},
            {"email": "jane@acme.com", "responseStatus": "accepted", "displayName": "Jane"},
        ],
    }
    event.update(overrides)
    return event


def _pages_response(events: list[dict], sync_token: str = "token-1") -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"items": events, "nextSyncToken": sync_token}
    return response


class TestCalendarSync(BaseTest):
    def setUp(self):
        super().setUp()
        self.integration = self._create_integration()

    def _create_integration(self):
        return Integration.objects.create(
            team=self.team,
            kind="google-calendar",
            integration_id="google-sub-1",
            config={"email": "csm@posthog.com", "refreshed_at": 9999999999, "expires_in": 3600},
            sensitive_config={"access_token": "ACCESS", "refresh_token": "REFRESH"},
        )

    def _sync(
        self, responses: list[MagicMock], person_uuids: dict[str, str] | None = None
    ) -> calendar_sync.CalendarSyncCounts:
        with (
            patch.object(calendar_sync, "_person_uuids_by_email", return_value=person_uuids or {}),
            patch.object(calendar_sync, "google_workspace_request", side_effect=responses),
        ):
            return calendar_sync.sync_calendar_integration(self.integration.id, self.team.id)

    def test_upserts_meeting_with_participants_and_matches_by_email_domain(self):
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Acme", external_id="acme")
        account.properties = {"email_domains": ["acme.com"]}
        account.save()

        counts = self._sync([_pages_response([_event()])])

        meeting = Meeting.objects.for_team(self.team.id).get()
        assert meeting.account_id == account.id
        assert meeting.title == "Quarterly review"
        assert meeting.status == MeetingStatus.CONFIRMED
        participants = {p.email: p for p in MeetingParticipant.objects.for_team(self.team.id)}
        assert set(participants) == {"csm@posthog.com", "jane@acme.com"}
        assert participants["jane@acme.com"].response_status == "accepted"
        assert counts.matched == 1
        self.integration.refresh_from_db()
        assert self.integration.config["calendar_sync_token"] == "token-1"

    def test_resync_of_same_event_updates_one_row(self):
        self._sync([_pages_response([_event()])])
        self._sync([_pages_response([_event(summary="Renamed")])])

        meeting = Meeting.objects.for_team(self.team.id).get()
        assert meeting.title == "Renamed"

    def test_recurring_instances_get_separate_rows(self):
        instances = [
            _event(
                id="series_20260804",
                recurringEventId="series",
                originalStartTime={"dateTime": "2026-08-04T15:00:00+00:00"},
            ),
            _event(
                id="series_20260811",
                recurringEventId="series",
                originalStartTime={"dateTime": "2026-08-11T15:00:00+00:00"},
                start={"dateTime": "2026-08-11T15:00:00+00:00"},
            ),
        ]
        self._sync([_pages_response(instances)])
        assert Meeting.objects.for_team(self.team.id).count() == 2

    def test_private_and_internal_only_events_are_never_stored(self):
        events = [
            _event(visibility="private"),
            _event(
                iCalUID="uid-internal@google.com",
                attendees=[
                    {"email": "csm@posthog.com", "responseStatus": "accepted"},
                    {"email": "colleague@posthog.com", "responseStatus": "accepted"},
                ],
            ),
        ]
        counts = self._sync([_pages_response(events)])
        assert Meeting.objects.for_team(self.team.id).count() == 0
        assert counts.skipped == 2

    def test_event_made_private_after_storage_is_deleted(self):
        self._sync([_pages_response([_event()])])
        assert Meeting.objects.for_team(self.team.id).count() == 1

        self._sync([_pages_response([_event(visibility="private")])])
        assert Meeting.objects.for_team(self.team.id).count() == 0

    def test_cancelled_event_keeps_row_flagged_cancelled(self):
        self._sync([_pages_response([_event()])])
        counts = self._sync([_pages_response([{"iCalUID": "uid-1@google.com", "status": "cancelled"}])])

        meeting = Meeting.objects.for_team(self.team.id).get()
        assert meeting.status == MeetingStatus.CANCELLED
        assert counts.cancelled == 1

    def test_stale_sync_token_falls_back_to_full_relist(self):
        self.integration.config["calendar_sync_token"] = "stale"
        self.integration.save()
        gone = MagicMock(status_code=410)
        counts = self._sync([gone, _pages_response([_event()], sync_token="fresh")])

        assert counts.upserted == 1
        self.integration.refresh_from_db()
        assert self.integration.config["calendar_sync_token"] == "fresh"

    @parameterized.expand([(5,), (15,), (30,), (60,)])
    @time_machine.travel("2026-09-25T12:00:00Z", tick=False)
    def test_collector_honors_configured_cadence_boundary(self, interval_minutes: int) -> None:
        now = timezone.now()
        self.integration.config.update(
            {
                calendar_sync.SYNC_INTERVAL_CONFIG_KEY: interval_minutes,
                calendar_sync.LAST_SYNCED_AT_CONFIG_KEY: (
                    now - timedelta(minutes=interval_minutes) + timedelta(seconds=1)
                ).isoformat(),
            }
        )
        self.integration.save(update_fields=["config"])

        assert temporal_calendar_sync._collect_calendar_integrations() == []

        self.integration.config[calendar_sync.LAST_SYNCED_AT_CONFIG_KEY] = (
            now - timedelta(minutes=interval_minutes)
        ).isoformat()
        self.integration.save(update_fields=["config"])
        selected = temporal_calendar_sync._collect_calendar_integrations()

        assert [item.integration_id for item in selected] == [self.integration.id]
        self.integration.refresh_from_db(fields=["config"])
        assert calendar_sync.SYNC_ATTEMPTED_AT_CONFIG_KEY not in self.integration.config

    @time_machine.travel("2026-09-25T12:00:00Z", tick=False)
    def test_failed_sync_clears_active_marker_and_waits_for_its_cadence(self) -> None:
        self.integration.config[calendar_sync.SYNC_INTERVAL_CONFIG_KEY] = 5
        self.integration.save(update_fields=["config"])
        error_response = MagicMock(status_code=500, text="Google Calendar unavailable")

        with self.assertRaises(calendar_sync.CalendarSyncError):
            self._sync([error_response])

        self.integration.refresh_from_db(fields=["config"])
        assert calendar_sync.SYNC_STARTED_AT_CONFIG_KEY not in self.integration.config
        assert self.integration.config[calendar_sync.SYNC_ATTEMPTED_AT_CONFIG_KEY] == timezone.now().isoformat()
        assert temporal_calendar_sync._collect_calendar_integrations() == []

        with time_machine.travel("2026-09-25T12:05:00Z", tick=False):
            selected = temporal_calendar_sync._collect_calendar_integrations()

        assert [item.integration_id for item in selected] == [self.integration.id]

    @time_machine.travel("2026-09-25T12:00:00Z", tick=False)
    def test_collector_waits_for_retry_window(self) -> None:
        self.integration.config[calendar_sync.SYNC_RETRY_AT_CONFIG_KEY] = (
            timezone.now() + timedelta(minutes=5)
        ).isoformat()
        self.integration.save(update_fields=["config"])

        assert temporal_calendar_sync._collect_calendar_integrations() == []

        with time_machine.travel("2026-09-25T12:05:00Z", tick=False):
            selected = temporal_calendar_sync._collect_calendar_integrations()

        assert [item.integration_id for item in selected] == [self.integration.id]

    def test_collector_limits_each_run_to_two_hundred_accounts(self) -> None:
        Integration.objects.bulk_create(
            [
                Integration(
                    team=self.team,
                    kind="google-calendar",
                    integration_id=f"google-sub-{index + 2}",
                )
                for index in range(temporal_calendar_sync.MAX_SYNCS_PER_RUN)
            ]
        )

        assert len(temporal_calendar_sync._collect_calendar_integrations()) == 200

    def test_backfill_uses_the_date_range_without_changing_the_incremental_cursor(self) -> None:
        self.integration.config["calendar_sync_token"] = "existing"
        self.integration.save(update_fields=["config"])
        start_at = datetime(2026, 7, 1, tzinfo=UTC)
        end_at = datetime(2026, 8, 1, tzinfo=UTC)

        first_page = _pages_response([_event()])
        first_page.json.return_value = {"items": [_event()], "nextPageToken": "page-2"}
        with (
            patch.object(calendar_sync, "_person_uuids_by_email", return_value={}),
            patch.object(
                calendar_sync,
                "google_workspace_request",
                side_effect=[first_page, _pages_response([])],
            ) as mock_get,
        ):
            result = calendar_sync.sync_calendar_integration_backfill_page(
                self.integration.id,
                self.team.id,
                start_at=start_at,
                end_at=end_at,
                page_token=None,
            )
            final_result = calendar_sync.sync_calendar_integration_backfill_page(
                self.integration.id,
                self.team.id,
                start_at=start_at,
                end_at=end_at,
                page_token=result.next_page_token,
            )

        assert result.counts.upserted == 1
        assert result.next_page_token == "page-2"
        assert final_result.next_page_token is None
        first_params = mock_get.call_args_list[0].kwargs["params"]
        second_params = mock_get.call_args_list[1].kwargs["params"]
        assert first_params["timeMin"] == start_at.isoformat()
        assert first_params["timeMax"] == end_at.isoformat()
        assert "syncToken" not in first_params
        assert second_params["pageToken"] == "page-2"
        self.integration.refresh_from_db()
        assert self.integration.config["calendar_sync_token"] == "existing"
        assert "calendar_last_synced_at" not in self.integration.config

    def test_known_email_matches_account_on_personal_domain(self):
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Kwak Bros", external_id="kwak")
        account.properties = {"known_emails": ["hector032716@gmail.com"]}
        account.save()

        event = _event(
            attendees=[
                {"email": "csm@posthog.com", "responseStatus": "accepted"},
                {"email": "hector032716@gmail.com", "responseStatus": "accepted"},
            ]
        )
        self._sync([_pages_response([event])])
        assert Meeting.objects.for_team(self.team.id).get().account_id == account.id

    @patch(
        "products.customer_analytics.backend.logic.email_account_matching.resolve_group_keys_by_email",
        return_value={"jane@acme.com": "acme"},
    )
    def test_matches_account_via_person_group(self, _mock_group_keys: MagicMock) -> None:
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save()
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Acme", external_id="acme")

        counts = self._sync([_pages_response([_event()])])

        assert Meeting.objects.for_team(self.team.id).get().account_id == account.id
        assert counts.matched == 1

    def test_removed_attendee_is_deleted_on_resync(self):
        self._sync([_pages_response([_event()])])
        assert MeetingParticipant.objects.for_team(self.team.id).count() == 2

        only_organizer = _event(
            attendees=[
                {"email": "csm@posthog.com", "responseStatus": "accepted"},
                {"email": "other@acme.com", "responseStatus": "accepted"},
            ]
        )
        self._sync([_pages_response([only_organizer])])
        emails = set(MeetingParticipant.objects.for_team(self.team.id).values_list("email", flat=True))
        assert emails == {"csm@posthog.com", "other@acme.com"}

    def test_resolved_person_uuid_is_stored_on_participants(self):
        person_uuid = "0198b6f3-0000-0000-0000-000000000001"
        self._sync([_pages_response([_event()])], person_uuids={"jane@acme.com": person_uuid})

        participants = {p.email: p for p in MeetingParticipant.objects.for_team(self.team.id)}
        assert str(participants["jane@acme.com"].person_id) == person_uuid
        assert participants["csm@posthog.com"].person_id is None

    @patch("products.customer_analytics.backend.logic.email_account_matching.resolve_group_keys_by_email")
    def test_ambiguous_email_domain_does_not_fall_through_to_person_group(self, mock_group_keys: MagicMock) -> None:
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save(update_fields=["account_group_type_index"])
        Account.objects.for_team(self.team.id).create(team=self.team, name="Grouped", external_id="group-account")
        mock_group_keys.side_effect = lambda _team_id, emails, _index: {
            email: "group-account" for email in emails if email == "member@example.com"
        }
        for name in ("First", "Second"):
            account = Account.objects.for_team(self.team.id).create(team=self.team, name=name, external_id=name.lower())
            account.properties = {"email_domains": ["example.com"]}
            account.save()

        event = _event(attendees=[{"email": "member@example.com", "responseStatus": "accepted"}])
        self._sync([_pages_response([event])])
        assert Meeting.objects.for_team(self.team.id).get().account_id is None

    @parameterized.expand(
        [
            ("known_email", {"known_emails": [" Jane@Acme.com "]}),
            ("email_domain", {"email_domains": ["@Acme.com"]}),
        ]
    )
    def test_rematches_unassigned_meeting_after_account_matching_changes(
        self, _name: str, properties: dict[str, list[str]]
    ) -> None:
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Acme", external_id="acme")
        meeting = Meeting.objects.for_team(self.team.id).create(
            team=self.team,
            ical_uid=f"unassigned-{_name}",
            start_time="2026-08-04T15:00:00Z",
        )
        MeetingParticipant.objects.for_team(self.team.id).create(team=self.team, meeting=meeting, email="jane@acme.com")
        account.properties = properties
        account.save()

        updated = calendar_sync.rematch_account_meetings(self.team.id, str(account.id))

        meeting.refresh_from_db()
        assert updated == 1
        assert meeting.account_id == account.id
