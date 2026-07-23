from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from rest_framework import serializers as drf_serializers

from posthog.schema import HogQLQuery

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Organization, Team

from products.actions.backend.models.action import Action
from products.autoresearch.backend.labeling import build_target_condition
from products.autoresearch.backend.serializers import resolve_target


class TestBuildTargetCondition(APIBaseTest):
    def test_event_target_emits_bound_predicate(self):
        cond, values = build_target_condition(target_event="$pageview", target_definition=None, team=None)
        assert cond == "event = {target}"
        assert values == {"target": "$pageview"}

    def test_event_type_definition_still_uses_target_event(self):
        cond, values = build_target_condition(
            target_event="signed_up", target_definition={"type": "event"}, team=self.team
        )
        assert cond == "event = {target}"
        assert values == {"target": "signed_up"}

    def test_action_target_compiles_to_self_contained_fragment(self):
        action = Action.objects.create(
            team=self.team,
            name="Interacted with file",
            steps_json=[{"event": "uploaded_file"}, {"event": "downloaded_file"}],
        )
        cond, values = build_target_condition(
            target_event="", target_definition={"type": "action", "action_id": action.id}, team=self.team
        )
        # Self-contained: constants inlined + escaped by the printer, so no bound values.
        assert values == {}
        assert "uploaded_file" in cond
        assert "downloaded_file" in cond

    def test_action_target_requires_action_id(self):
        with self.assertRaises(ValueError):
            build_target_condition(target_event="", target_definition={"type": "action"}, team=self.team)

    def test_action_target_requires_team(self):
        with self.assertRaises(ValueError):
            build_target_condition(target_event="", target_definition={"type": "action", "action_id": 1}, team=None)

    def test_action_target_is_team_scoped(self):
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other")
        action = Action.objects.create(team=other_team, name="Foreign", steps_json=[{"event": "uploaded_file"}])
        # Resolving a foreign action against self.team must not leak it.
        with self.assertRaises(Action.DoesNotExist):
            build_target_condition(
                target_event="", target_definition={"type": "action", "action_id": action.id}, team=self.team
            )


class TestResolveTarget(APIBaseTest):
    def test_event_target_normalizes_definition(self):
        event, definition = resolve_target(team=self.team, target_event="$pageview", target_definition=None)
        assert event == "$pageview"
        assert definition == {"type": "event"}

    def test_empty_event_target_raises(self):
        with self.assertRaises(drf_serializers.ValidationError):
            resolve_target(team=self.team, target_event="", target_definition=None)

    def test_action_target_backfills_event_from_action_name(self):
        action = Action.objects.create(
            team=self.team, name="Interacted with file", steps_json=[{"event": "uploaded_file"}]
        )
        event, definition = resolve_target(
            team=self.team, target_event="", target_definition={"type": "action", "action_id": action.id}
        )
        assert event == "Interacted with file"
        assert definition == {"type": "action", "action_id": action.id}

    def test_action_target_keeps_explicit_event_label(self):
        action = Action.objects.create(team=self.team, name="Some action", steps_json=[{"event": "uploaded_file"}])
        event, definition = resolve_target(
            team=self.team,
            target_event="custom label",
            target_definition={"type": "action", "action_id": action.id},
        )
        assert event == "custom label"

    def test_missing_action_id_raises(self):
        with self.assertRaises(drf_serializers.ValidationError):
            resolve_target(team=self.team, target_event="", target_definition={"type": "action"})

    def test_foreign_action_raises(self):
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other")
        action = Action.objects.create(team=other_team, name="Foreign", steps_json=[{"event": "uploaded_file"}])
        with self.assertRaises(drf_serializers.ValidationError):
            resolve_target(
                team=self.team, target_event="", target_definition={"type": "action", "action_id": action.id}
            )


class TestTargetConditionAgainstClickhouse(ClickhouseTestMixin, APIBaseTest):
    def _count(self, cond: str, values: dict) -> int:
        sql = f"SELECT count() FROM events WHERE {cond}"
        runner = HogQLQueryRunner(query=HogQLQuery(query=sql, values=values), team=self.team)
        result = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        return int(result.results[0][0]) if result.results else 0

    def test_action_predicate_selects_action_matching_events(self):
        _create_person(team_id=self.team.pk, distinct_ids=["u1"])
        for event in ["uploaded_file", "uploaded_file", "downloaded_file", "$pageview", "$pageview", "$pageview"]:
            _create_event(team=self.team, event=event, distinct_id="u1")
        flush_persons_and_events()

        action = Action.objects.create(
            team=self.team,
            name="Interacted with file",
            steps_json=[{"event": "uploaded_file"}, {"event": "downloaded_file"}],
        )

        action_cond, action_values = build_target_condition(
            target_event="", target_definition={"type": "action", "action_id": action.id}, team=self.team
        )
        event_cond, event_values = build_target_condition(
            target_event="$pageview", target_definition=None, team=self.team
        )

        # 2 uploaded_file + 1 downloaded_file match the action; 3 $pageview match the event target.
        assert self._count(action_cond, action_values) == 3
        assert self._count(event_cond, event_values) == 3

    def test_action_with_property_filter(self):
        _create_person(team_id=self.team.pk, distinct_ids=["u2"])
        _create_event(team=self.team, event="uploaded_file", distinct_id="u2", properties={"size": "large"})
        _create_event(team=self.team, event="uploaded_file", distinct_id="u2", properties={"size": "small"})
        flush_persons_and_events()

        action = Action.objects.create(
            team=self.team,
            name="Large upload",
            steps_json=[{"event": "uploaded_file", "properties": [{"key": "size", "value": "large", "type": "event"}]}],
        )
        cond, values = build_target_condition(
            target_event="", target_definition={"type": "action", "action_id": action.id}, team=self.team
        )
        assert self._count(cond, values) == 1
