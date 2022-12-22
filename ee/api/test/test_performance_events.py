import uuid

from ee.api.test.base import APILicensedTest
from ee.test.fixtures.performance_event_fixtures import create_performance_event
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest


class TestLicensedPerformanceEvents(APILicensedTest):
    def test_performance_lists_events_by_session_id(self):
        session_id = str(uuid.uuid4())
        create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
        create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
        create_performance_event(self.team.id, "user_1", session_id, current_url="https://posthog.com")
        create_performance_event(self.team.id, "user_2", session_id + "2", current_url="https://posthog.com")

        res = self.client.get(f"/api/projects/@current/performance_events?session_id={session_id}")
        assert res.status_code == 200
        assert len(res.json()["results"]) == 3

    def test_performance_events_doesnt_list_other_team(self):
        session_id = str(uuid.uuid4())
        team = Team.objects.create(name="Test Team", organization=self.organization)
        create_performance_event(team.id, "user_1", session_id, current_url="https://posthog.com")

        res = self.client.get(f"/api/projects/@current/performance_events?session_id={session_id}")
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
