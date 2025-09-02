import pytest
from posthog.test.base import BaseTest, _create_event, _create_person, flush_persons_and_events

from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_response_in_tests

from posthog.models import Action
from posthog.models.utils import UUIDT


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name, steps_json=[{"event": name}])
    return action


def _create_action_with_property(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(
        team=team,
        name=name,
        steps_json=[
            {
                "event": name,
                "url": "https://posthog.com/feedback/123?vip=1",
                "url_matching": "exact",
            }
        ],
    )
    return action


class TestAction(BaseTest):
    maxDiff = None

    def _create_random_events(self) -> str:
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        _create_person(
            properties={"$os": "Chrome", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        _create_event(
            distinct_id="bla",
            event=random_uuid,
            team=self.team,
            properties={"$current_url": "https://posthog.com/feedback/123?vip=1"},
        )
        _create_event(distinct_id="bla", event=random_uuid + "::extra", team=self.team)
        flush_persons_and_events()
        return random_uuid

    def test_matches_action_name(self):
        random_uuid = self._create_random_events()
        _create_action(team=self.team, name=random_uuid)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE matchesAction('{random_uuid}')",
            self.team,
        )

        assert response.results is not None
        assert len(response.results) == 1
        assert response.results[0][0] == random_uuid

    def test_matches_action_id(self):
        random_uuid = self._create_random_events()
        action = _create_action(team=self.team, name=random_uuid)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE matchesAction({action.pk})",
            self.team,
        )
        assert response.results is not None
        assert len(response.results) == 1
        assert response.results[0][0] == random_uuid

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_matches_action_with_alias(self):
        random_uuid = self._create_random_events()
        _create_action_with_property(team=self.team, name=random_uuid)
        response = execute_hogql_query(
            f"SELECT event FROM events AS e WHERE matchesAction('{random_uuid}')",
            self.team,
        )

        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot  # type: ignore
        assert response.results is not None
        assert len(response.results) == 1
        assert response.results[0][0] == random_uuid
