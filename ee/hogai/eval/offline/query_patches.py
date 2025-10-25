from collections import defaultdict
from typing import Literal

from posthog.schema import (
    ActorsPropertyTaxonomyQueryResponse,
    ActorsPropertyTaxonomyResponse,
    EventTaxonomyItem,
    EventTaxonomyQueryResponse,
    TeamTaxonomyItem,
    TeamTaxonomyQueryResponse,
)

from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner

# This is a global state that is used to store the patched results for the team taxonomy query.
TEAM_TAXONOMY_QUERY_DATA_SOURCE: dict[int, list[TeamTaxonomyItem]] = {}


class PatchedTeamTaxonomyQueryRunner(TeamTaxonomyQueryRunner):
    def _calculate(self):
        results: list[TeamTaxonomyItem] = []
        if precomputed_results := TEAM_TAXONOMY_QUERY_DATA_SOURCE.get(self.team.id):
            results = precomputed_results
        return TeamTaxonomyQueryResponse(results=results, modifiers=self.modifiers)


# This is a global state that is used to store the patched results for the event taxonomy query.
EVENT_TAXONOMY_QUERY_DATA_SOURCE: dict[int, dict[str | int, list[EventTaxonomyItem]]] = defaultdict(dict)


class PatchedEventTaxonomyQueryRunner(EventTaxonomyQueryRunner):
    def _calculate(self):
        results: list[EventTaxonomyItem] = []
        team_data = EVENT_TAXONOMY_QUERY_DATA_SOURCE.get(self.team.id, {})
        if self.query.event in team_data:
            results = team_data[self.query.event]
        elif self.query.actionId in team_data:
            results = team_data[self.query.actionId]
        return EventTaxonomyQueryResponse(results=results, modifiers=self.modifiers)


# This is a global state that is used to store the patched results for the actors property taxonomy query.
ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE: dict[
    int, dict[int | Literal["person"], dict[str, ActorsPropertyTaxonomyResponse]]
] = defaultdict(lambda: defaultdict(dict))


class PatchedActorsPropertyTaxonomyQueryRunner(ActorsPropertyTaxonomyQueryRunner):
    def _calculate(self):
        key: int | Literal["person"] = (
            self.query.groupTypeIndex if isinstance(self.query.groupTypeIndex, int) else "person"
        )
        if (
            self.team.id in ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE
            and key in ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[self.team.id]
        ):
            data = ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[self.team.id][key]
            result: list[ActorsPropertyTaxonomyResponse] = []
            for prop in self.query.properties:
                result.append(data.get(prop, ActorsPropertyTaxonomyResponse(sample_values=[], sample_count=0)))
        else:
            result = [ActorsPropertyTaxonomyResponse(sample_values=[], sample_count=0) for _ in self.query.properties]
        return ActorsPropertyTaxonomyQueryResponse(results=result, modifiers=self.modifiers)
