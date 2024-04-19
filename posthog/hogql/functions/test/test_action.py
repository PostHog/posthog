import pytest

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_response_in_tests
from posthog.models import Action, ActionStep
from posthog.models.utils import UUIDT
from posthog.test.base import (
    BaseTest,
    _create_person,
    _create_event,
    flush_persons_and_events,
)

elements_chain_match = lambda x: parse_expr("match(elements_chain, {regex})", {"regex": ast.Constant(value=str(x))})
not_call = lambda x: ast.Call(name="not", args=[x])


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
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
        _create_event(distinct_id="bla", event=random_uuid, team=self.team)
        flush_persons_and_events()
        return random_uuid

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_matches_action_name(self):
        random_uuid = self._create_random_events()
        _create_action(team=self.team, name=random_uuid)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE matchesAction('{random_uuid}')",
            self.team,
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
        assert response.results is not None
        assert len(response.results) == 1
        assert response.results[0][0] == random_uuid

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_matches_action_id(self):
        random_uuid = self._create_random_events()
        action = _create_action(team=self.team, name=random_uuid)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE matchesAction({action.pk})",
            self.team,
            pretty=False,
        )
        assert pretty_print_response_in_tests(response, self.team.pk) == self.snapshot
        assert response.results is not None
        assert len(response.results) == 1
        assert response.results[0][0] == random_uuid
