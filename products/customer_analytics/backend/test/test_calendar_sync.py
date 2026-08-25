from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

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

    def _sync(
        self, responses: list[MagicMock], person_uuids: dict[str, str] | None = None
    ) -> calendar_sync.CalendarSyncCounts:
        with (
            patch.object(calendar_sync, "_person_uuids_by_email", return_value=person_uuids or {}),
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

    def test_ambiguous_email_domain_matches_nothing(self):
        for name in ("Acme US", "Acme EU"):
            account = Account.objects.for_team(self.team.id).create(
                team=self.team, name=name, external_id=name.lower().replace(" ", "-")
            )
            account.properties = {"email_domains": ["acme.com"]}
            account.save()

        self._sync([_pages_response([_event()])])
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
