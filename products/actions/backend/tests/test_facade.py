from posthog.test.base import APIBaseTest

from posthog.models import Team

from products.actions.backend.facade.api import action_filter_conditions
from products.actions.backend.models.action import Action


class TestActionFilterConditions(APIBaseTest):
    def _action(self, name: str, **kwargs) -> Action:
        kwargs.setdefault("steps_json", [{"event": "checkout completed"}])
        kwargs.setdefault("team", self.team)
        return Action.objects.create(name=name, **kwargs)

    def test_only_actions_that_can_filter_come_back(self):
        # A caller uses the returned keys to decide which actions are usable, so an action that
        # cannot narrow anything must be absent rather than present with a condition that matches
        # everything. A stepless action is the trap: `steps_to_expr` compiles it to a constant true.
        live = self._action("Completed checkout")
        stepless = self._action("Never finished", steps_json=[])
        deleted = self._action("Removed", deleted=True)

        conditions = action_filter_conditions(team=self.team, action_ids=[live.id, stepless.id, deleted.id])

        assert list(conditions) == [live.id]

    def test_an_action_outside_the_project_is_never_returned(self):
        # The ids reach this function from a search, so trusting them would let a caller compile a
        # filter against another project's action.
        other_team = Team.objects.create(organization=self.organization, name="other")
        theirs = Action.objects.create(team=other_team, name="Theirs", steps_json=[{"event": "checkout completed"}])

        assert action_filter_conditions(team=self.team, action_ids=[theirs.id]) == {}
