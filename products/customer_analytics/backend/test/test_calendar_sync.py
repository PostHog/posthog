from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.customer_analytics.backend.logic import calendar_sync
from products.customer_analytics.backend.models import Account, Meeting, MeetingParticipant, MeetingStatus


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
        from posthog.models.integration import Integration

        return Integration.objects.create(
            team=self.team,
            kind="google-calendar",
            integration_id="google-sub-1",
            config={"email": "csm@posthog.com", "refreshed_at": 9999999999, "expires_in": 3600},
            sensitive_config={"access_token": "ACCESS", "refresh_token": "REFRESH"},
        )

    def _sync(self, responses: list[MagicMock]) -> calendar_sync.CalendarSyncCounts:
        with (
            patch.object(calendar_sync, "_group_keys_via_persons", return_value={}),
            patch.object(calendar_sync.requests, "get", side_effect=responses),
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

    def test_ambiguous_email_domain_matches_nothing(self):
        for name in ("Acme US", "Acme EU"):
            account = Account.objects.for_team(self.team.id).create(
                team=self.team, name=name, external_id=name.lower().replace(" ", "-")
            )
            account.properties = {"email_domains": ["acme.com"]}
            account.save()

        self._sync([_pages_response([_event()])])
        assert Meeting.objects.for_team(self.team.id).get().account_id is None
