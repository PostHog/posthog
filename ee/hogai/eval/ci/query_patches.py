from typing import TYPE_CHECKING

from posthog.hogql_queries.ai.actors_property_taxonomy_query_runner import ActorsPropertyTaxonomyQueryRunner
from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.schema import EventTaxonomyItem, EventTaxonomyQueryResponse, TeamTaxonomyItem, TeamTaxonomyQueryResponse

from .oracles import property_value_oracle

try:
    from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
except ImportError:
    CORE_FILTER_DEFINITIONS_BY_GROUP = {}

if TYPE_CHECKING:
    pass


# This is a global state that is used to store the patched results for the team taxonomy query.
TEAM_TAXONOMY_QUERY_DATA_SOURCE: dict[int, list[TeamTaxonomyItem]] = {}


class PatchedTeamTaxonomyQueryRunner(TeamTaxonomyQueryRunner):
    def calculate(self):
        results: list[TeamTaxonomyItem] = []
        if precomputed_results := TEAM_TAXONOMY_QUERY_DATA_SOURCE.get(self.team.id):
            results = precomputed_results
        return TeamTaxonomyQueryResponse(results=results, modifiers=self.modifiers)


# This is a global state that is used to store the patched results for the event taxonomy query.
EVENT_TAXONOMY_QUERY_DATA_SOURCE: dict[int, dict[str | int, list[EventTaxonomyItem]]] = {}


class PatchedEventTaxonomyQueryRunner(EventTaxonomyQueryRunner):
    def calculate(self):
        results: list[EventTaxonomyItem] = []
        team_data = EVENT_TAXONOMY_QUERY_DATA_SOURCE.get(self.team.id, {})
        if self.query.event in team_data:
            results = team_data[self.query.event]
        elif self.query.actionId in team_data:
            results = team_data[self.query.actionId]
        return EventTaxonomyQueryResponse(results=results, modifiers=self.modifiers)


ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE: dict[int, dict[str | int, list[EventTaxonomyItem]]] = {}


class PatchedActorsPropertyTaxonomyQueryRunner(ActorsPropertyTaxonomyQueryRunner):
    def calculate(self):
        return property_value_oracle.synthesize_event("Event", self.query.property, self.query.property_type)
