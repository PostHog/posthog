import copy
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List

from django.conf import settings
from django.db.models.expressions import F
from django.utils import timezone
from sentry_sdk.api import capture_exception

from ee.clickhouse.queries.stickiness.stickiness_actors import ClickhouseStickinessActors
from ee.clickhouse.queries.stickiness.stickiness_event_query import StickinessEventsQuery
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL, INSERT_COHORT_ALL_PEOPLE_SQL, PERSON_STATIC_COHORT_TABLE
from posthog.client import sync_execute
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.queries.base import handle_compare
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.utils import encode_get_request_params


class ClickhouseStickiness:
    def run(self, filter: StickinessFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:

        response = []
        for entity in filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                entity.name = Action.objects.only("name").get(team=team, pk=entity.id).name

            entity_resp = handle_compare(filter=filter, func=self._serialize_entity, team=team, entity=entity)
            response.extend(entity_resp)
        return response

    def stickiness(self, entity: Entity, filter: StickinessFilter, team: Team) -> Dict[str, Any]:
        events_query, event_params = StickinessEventsQuery(entity, filter, team).get_query()

        query = f"""
        SELECT countDistinct(aggregation_target), num_intervals FROM ({events_query})
        WHERE num_intervals <= %(num_intervals)s
        GROUP BY num_intervals
        ORDER BY num_intervals
        SETTINGS optimize_move_to_prewhere = 0
        """

        counts = sync_execute(query, {**event_params, "num_intervals": filter.total_intervals})
        return self.process_result(counts, filter, entity)

    def people(self, target_entity: Entity, filter: StickinessFilter, team: Team, request, *args, **kwargs):
        _, serialized_actors = ClickhouseStickinessActors(entity=target_entity, filter=filter, team=team).get_actors()
        return serialized_actors

    def process_result(self, counts: List, filter: StickinessFilter, entity: Entity) -> Dict[str, Any]:
        response: Dict[int, int] = {}
        for result in counts:
            response[result[1]] = result[0]

        labels = []
        data = []
        for day in range(1, filter.total_intervals):
            label = "{} {}{}".format(day, filter.interval, "s" if day > 1 else "")
            labels.append(label)
            data.append(response[day] if day in response else 0)
        filter_params = filter.to_params()

        return {
            "labels": labels,
            "days": [day for day in range(1, filter.total_intervals)],
            "data": data,
            "count": sum(data),
            "filter": filter_params,
            "persons_urls": self._get_persons_url(filter, entity),
        }

    def _serialize_entity(self, entity: Entity, filter: StickinessFilter, team: Team) -> List[Dict[str, Any]]:
        serialized: Dict[str, Any] = {
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

    def _get_persons_url(self, filter: StickinessFilter, entity: Entity) -> List[Dict[str, Any]]:
        persons_url = []
        for interval_idx in range(1, filter.total_intervals):
            filter_params = filter.to_params()
            extra_params = {
                "stickiness_days": interval_idx,
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
            }
            parsed_params: Dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {"filter": extra_params, "url": f"api/person/stickiness/?{urllib.parse.urlencode(parsed_params)}",}
            )
        return persons_url


def insert_stickiness_people_into_cohort(cohort: Cohort, target_entity: Entity, filter: StickinessFilter) -> None:
    content_sql, params = ClickhouseStickinessActors(
        entity=target_entity, filter=filter, team=cohort.team
    ).actor_query()

    try:
        sync_execute(
            INSERT_COHORT_ALL_PEOPLE_SQL.format(
                content_sql=content_sql,
                latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
                cohort_table=PERSON_STATIC_COHORT_TABLE,
                GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(cohort.team_id),
            ),
            {"cohort_id": cohort.pk, "_timestamp": datetime.now(), **params},
        )
        cohort.is_calculating = False
        cohort.last_calculation = timezone.now()
        cohort.errors_calculating = 0
        cohort.save()
    except Exception as err:
        if settings.DEBUG:
            raise err
        cohort.is_calculating = False
        cohort.errors_calculating = F("errors_calculating") + 1
        cohort.save()
        capture_exception(err)
