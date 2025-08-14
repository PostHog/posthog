from collections import defaultdict
from typing import Literal

from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.schema import (
    ActorsPropertyTaxonomyQueryResponse,
    ActorsPropertyTaxonomyResponse,
    EventTaxonomyItem,
    EventTaxonomyQueryResponse,
    TeamTaxonomyItem,
    TeamTaxonomyQueryResponse,
)

# This is a global state that is used to store the patched results for the team taxonomy query.
TEAM_TAXONOMY_QUERY_DATA_SOURCE: dict[int, list[TeamTaxonomyItem]] = {}


class PatchedTeamTaxonomyQueryRunner(TeamTaxonomyQueryRunner):
    def calculate(self):
        results: list[TeamTaxonomyItem] = []
        if precomputed_results := TEAM_TAXONOMY_QUERY_DATA_SOURCE.get(self.team.id):
            results = precomputed_results
        return TeamTaxonomyQueryResponse(results=results, modifiers=self.modifiers)


# This is a global state that is used to store the patched results for the event taxonomy query.
EVENT_TAXONOMY_QUERY_DATA_SOURCE: dict[int, dict[str, list[EventTaxonomyItem]]] = defaultdict(dict)


class PatchedEventTaxonomyQueryRunner(EventTaxonomyQueryRunner):
    def calculate(self):
        results: list[EventTaxonomyItem] = []
        team_data = EVENT_TAXONOMY_QUERY_DATA_SOURCE.get(self.team.id, {})
        if self.query.event in team_data:
            results = team_data[self.query.event]
        elif self.query.actionId in team_data:
            results = team_data[self.query.actionId]
        return EventTaxonomyQueryResponse(results=results, modifiers=self.modifiers)


# This is a global state that is used to store the patched results for the actors property taxonomy query.
ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE: dict[int, dict[int | Literal["person"], ActorsPropertyTaxonomyResponse]] = (
    defaultdict(dict)
)


class PatchedActorsPropertyTaxonomyQueryRunner(ActorsPropertyTaxonomyQueryRunner):
    def calculate(self):
        key = self.query.group_type_index or "person"
        if snapshotted_query := ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE.get(self.team.id, {}).get(key):
            result = snapshotted_query
        else:
            result = ActorsPropertyTaxonomyResponse(sample_values=[], sample_count=0)
        return ActorsPropertyTaxonomyQueryResponse(results=result, modifiers=self.modifiers)
