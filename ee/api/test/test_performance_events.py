import uuid

from freezegun import freeze_time

from ee.api.test.base import APILicensedTest
from ee.test.fixtures.performance_event_fixtures import create_performance_event
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest


class TestLicensedPerformanceEvents(APILicensedTest):
    def test_performance_errors_if_missing_params(self):
        res = self.client.get(f"/api/projects/@current/performance_events")
        assert res.status_code == 400
        assert res.json() == {
            "attr": "date_from",
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

    @freeze_time("2021-01-01T12:00:00Z")
    def test_performance_lists_events_by_session_id(self):
        session_id = str(uuid.uuid4())

        create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
        create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
        create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
        create_performance_event(self.team.id, "user_2", session_id + "2", current_url="https://posthog.com")

        res = self.client.get(
            f"/api/projects/@current/performance_events?session_id={session_id}&date_from=2021-01-01T00:00:00Z&date_to=2021-01-02T00:00:00Z"
        )
        assert res.status_code == 200
        assert len(res.json()["results"]) == 3

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
