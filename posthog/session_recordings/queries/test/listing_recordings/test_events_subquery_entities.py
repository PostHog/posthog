from posthog.test.base import APIBaseTest

from posthog.schema import ActionsNode, EventsNode, RecordingsQuery

from posthog.session_recordings.queries.sub_queries.events_subquery import ReplayFiltersEventsSubQuery


class TestEventsSubQueryEntities(APIBaseTest):
    def test_event_entity_without_type_defaults_to_events(self) -> None:
        # A malformed RecordingsQuery whose event dict is missing "type" used to raise
        # ValueError from Entity.__init__ and 500 the recordings list API. Entries in
        # `events` are events by definition, so the type is defaulted instead.
        query = RecordingsQuery(events=[{"id": "$pageview", "name": "$pageview"}])
        subquery = ReplayFiltersEventsSubQuery(team=self.team, query=query)

        entities = subquery.event_entities

        assert len(entities) == 1
        assert isinstance(entities[0], EventsNode)

    def test_action_entity_without_type_defaults_to_actions(self) -> None:
        query = RecordingsQuery(actions=[{"id": 123, "name": "signed up"}])
        subquery = ReplayFiltersEventsSubQuery(team=self.team, query=query)

        entities = subquery.action_entities

        assert len(entities) == 1
        assert isinstance(entities[0], ActionsNode)
