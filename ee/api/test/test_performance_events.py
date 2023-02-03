import datetime
import uuid

from freezegun import freeze_time

from ee.api.test.base import APILicensedTest
from ee.test.fixtures.performance_event_fixtures import create_performance_event
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest


class TestLicensedPerformanceEvents(APILicensedTest):
    def test_performance_errors_if_missing_date_from_params(self):
        res = self.client.get(f"/api/projects/@current/performance_events?session_id=1234")
        assert res.status_code == 400
        assert res.json() == {
            "attr": "date_from",
            "code": "required",
            "detail": "This field is required.",
            "type": "validation_error",
        }

    def test_performance_errors_if_missing_session_id_params(self):
        res = self.client.get(
            f"/api/projects/@current/performance_events?&date_from=2021-01-01T00:00:00Z&date_to=2021-01-02T00:00:00Z"
        )
        assert res.status_code == 400
        assert res.json() == {
            "attr": "session_id",
            "code": "required",
            "detail": "This field is required.",
            "type": "validation_error",
        }

    def test_list_reject_if_date_range_too_long(self):
        res = self.client.get(
            f"/api/projects/@current/performance_events?session_id=1234&date_from=2021-01-01T00:00:00Z&date_to=2021-01-06T00:00:00Z"
        )
        assert res.status_code == 200
        res = self.client.get(
            f"/api/projects/@current/performance_events?session_id=1234&date_from=2021-01-01T00:00:00Z&date_to=2021-01-10T00:00:00Z"
        )
        assert res.status_code == 400
        assert res.json() == {
            "attr": None,
            "code": "invalid_input",
            "detail": "Date range cannot be more than 7 days",
            "type": "validation_error",
        }

    # @freeze_time("2021-01-01T12:00:00Z")
    # def test_performance_lists_events_by_session_id(self):
    #     session_id = str(uuid.uuid4())
    #     now = datetime.datetime.now()
    #
    #     create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com", timestamp=now)
    #     create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com", timestamp=now)
    #     create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com", timestamp=now)
    #     create_performance_event(
    #         self.team.id, "user_2", session_id + "2", current_url="https://posthog.com", timestamp=now
    #     )
    #
    #     res = self.client.get(
    #         f"/api/projects/@current/performance_events?session_id={session_id}&date_from=2021-01-01T00:00:00Z&date_to=2021-01-02T00:00:00Z"
    #     )
    #     assert res.status_code == 200
    #     # NOTE: this test can be oddly flakey
    #     assert len(res.json()["results"]) == 3

    @freeze_time("2021-01-01T12:00:00Z")
    def test_performance_events_doesnt_list_other_team(self):
        session_id = str(uuid.uuid4())
        team = Team.objects.create(name="Test Team", organization=self.organization)
        create_performance_event(team.id, "user_1", session_id, current_url="https://posthog.com")

        res = self.client.get(
            f"/api/projects/@current/performance_events?session_id={session_id}&date_from=2021-01-01T00:00:00Z&date_to=2021-01-02T00:00:00Z"
        )
        assert res.status_code == 200
        assert len(res.json()["results"]) == 0

    def test_list_doesnt_return_out_of_range(self):
        session_id = str(uuid.uuid4())

        with freeze_time("2021-01-01T12:00:00Z"):
            create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
            create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
            create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
            create_performance_event(self.team.id, "user_2", session_id + "2", current_url="https://posthog.com")

        res = self.client.get(
            f"/api/projects/@current/performance_events?session_id={session_id}&date_from=2022-01-01T00:00:00Z&date_to=2022-01-02T00:00:00Z"
        )
        assert res.status_code == 200
        assert len(res.json()["results"]) == 0

    def test_list_recent_pageviews(self):

        # recent navigation matches if requesting at least six days
        create_performance_event(
            self.team.id,
            distinct_id="user_1",
            session_id="matching_session_one",
            current_url="https://posthog.com",
            entry_type="navigation",
            timestamp=datetime.datetime.now() - datetime.timedelta(days=6),
        )

        # recent navigation matches  if requesting at least 3 days
        create_performance_event(
            self.team.id,
            distinct_id="user_1",
            session_id="matching_session_two",
            current_url="https://posthog.com",
            entry_type="navigation",
            timestamp=datetime.datetime.now() - datetime.timedelta(days=2),
        )
        # recent resource does not match
        create_performance_event(
            self.team.id, "user_1", "non_matching_one", current_url="https://posthog.com", entry_type="resource"
        )
        # old navigation does not match
        create_performance_event(
            self.team.id,
            "user_2",
            "non_matching_two",
            current_url="https://posthog.com",
            entry_type="navigation",
            timestamp=datetime.datetime.fromisoformat("2008-04-10 11:47:58"),
        )

        seven_days_ago = datetime.datetime.now() - datetime.timedelta(days=7)
        res = self.client.get(
            f"/api/projects/@current/performance_events/recent_pageviews?date_from={seven_days_ago.isoformat()}"
        )
        self.assertEqual(res.status_code, 200, res.json())
        assert [r["session_id"] for r in res.json()["results"]] == ["matching_session_two", "matching_session_one"]

        three_days_ago = datetime.datetime.now() - datetime.timedelta(days=3)
        res = self.client.get(
            f"/api/projects/@current/performance_events/recent_pageviews?date_from={three_days_ago.isoformat()}"
        )
        self.assertEqual(res.status_code, 200, res.json())
        assert [r["session_id"] for r in res.json()["results"]] == ["matching_session_two"]

    def test_list_recent_pageviews_cannot_request_more_than_thirty_days(self):
        thirty_days_ago = datetime.datetime.now() - datetime.timedelta(days=30)
        thirty_one_days_ago = datetime.datetime.now() - datetime.timedelta(days=31)

        res = self.client.get(
            f"/api/projects/@current/performance_events/recent_pageviews?date_from={thirty_days_ago.isoformat()}"
        )
        assert res.status_code == 200

        res = self.client.get(
            f"/api/projects/@current/performance_events/recent_pageviews?date_from={thirty_one_days_ago.isoformat()}"
        )
        assert res.status_code == 400


class TestUnlicensedPerformanceEvents(APIBaseTest):
    def test_unlicensed_error(self):
        res = self.client.get(f"/api/projects/@current/performance_events?session_id=123")
        assert res.status_code == 402
        assert res.json() == {
            "attr": None,
            "code": "payment_required",
            "detail": "This feature is part of the premium PostHog offering. To use it, get a self-hosted license: https://license.posthog.com",
            "type": "server_error",
        }
