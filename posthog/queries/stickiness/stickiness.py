import copy
import urllib.parse
from typing import Any

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.queries.base import handle_compare
from posthog.queries.insight import insight_sync_execute
from posthog.queries.stickiness.stickiness_actors import StickinessActors
from posthog.queries.stickiness.stickiness_event_query import StickinessEventsQuery
from posthog.queries.util import correct_result_for_sampling
from posthog.utils import encode_get_request_params, generate_short_id


class Stickiness:
    event_query_class = StickinessEventsQuery
    actor_query_class = StickinessActors

    def run(self, filter: StickinessFilter, team: Team, *args, **kwargs) -> list[dict[str, Any]]:
        response = []
        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS and entity.id is not None:
                entity.name = Action.objects.only("name").get(team__project_id=team.project_id, pk=entity.id).name

            entity_resp = handle_compare(filter=filter, func=self._serialize_entity, team=team, entity=entity)
            response.extend(entity_resp)
        return response

    def stickiness(self, entity: Entity, filter: StickinessFilter, team: Team) -> dict[str, Any]:
        events_query, event_params = self.event_query_class(
            entity, filter, team, person_on_events_mode=team.person_on_events_mode
        ).get_query()

        query = f"""
        SELECT countDistinct(aggregation_target), num_intervals FROM ({events_query})
        WHERE num_intervals <= %(num_intervals)s
        GROUP BY num_intervals
        ORDER BY num_intervals
        """

        counts = insight_sync_execute(
            query,
            {
                **event_params,
                **filter.hogql_context.values,
                "num_intervals": filter.total_intervals,
            },
            query_type="stickiness",
            filter=filter,
            team_id=team.pk,
        )
        return self.process_result(counts, filter, entity)

    def people(
        self,
        target_entity: Entity,
        filter: StickinessFilter,
        team: Team,
        request,
        *args,
        **kwargs,
    ):
        _, serialized_actors, _ = self.actor_query_class(entity=target_entity, filter=filter, team=team).get_actors()
        return serialized_actors

    def process_result(self, counts: list, filter: StickinessFilter, entity: Entity) -> dict[str, Any]:
        response: dict[int, int] = {}
        for result in counts:
            response[result[1]] = result[0]

        labels = []
        data = []
        for day in range(1, filter.total_intervals):
            label = "{} {}{}".format(day, filter.interval, "s" if day > 1 else "")
            labels.append(label)
            data.append(
                correct_result_for_sampling(response[day], filter.sampling_factor, entity.math)
                if day in response
                else 0
            )
        filter_params = filter.to_params()

        return {
            "labels": labels,
            "days": list(range(1, filter.total_intervals)),
            "data": data,
            "count": sum(data),
            "filter": filter_params,
            "persons_urls": self._get_persons_url(filter, entity),
        }

    def _serialize_entity(self, entity: Entity, filter: StickinessFilter, team: Team) -> list[dict[str, Any]]:
        serialized: dict[str, Any] = {
            "action": entity.to_dict(),
            "label": entity.name,
            "count": 0,
            "data": [],
            "labels": [],
            "days": [],
        }
        response = []
        new_dict = copy.deepcopy(serialized)
        new_dict.update(self.stickiness(entity=entity, filter=filter, team=team))
        response.append(new_dict)
        return response

    def _get_persons_url(self, filter: StickinessFilter, entity: Entity) -> list[dict[str, Any]]:
        persons_url = []
        cache_invalidation_key = generate_short_id()
        for interval_idx in range(1, filter.total_intervals):
            filter_params = filter.to_params()
            extra_params = {
                "stickiness_days": interval_idx,
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "entity_order": entity.order,
            }
            parsed_params: dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {
                    "filter": extra_params,
                    "url": f"api/person/stickiness/?{urllib.parse.urlencode(parsed_params)}&cache_invalidation_key={cache_invalidation_key}",
                }
            )
        return persons_url
