from datetime import datetime
from typing import Callable, Dict, List, Tuple

from django.db.models.query import Prefetch
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.person import get_persons_by_uuids
from ee.clickhouse.queries.person_distinct_id_query import get_team_distinct_ids_query
from ee.clickhouse.queries.trends.trend_event_query import TrendsEventQuery
from ee.clickhouse.queries.trends.util import parse_response
from ee.clickhouse.queries.util import get_earliest_timestamp, parse_timestamps
from ee.clickhouse.sql.trends.lifecycle import LIFECYCLE_PEOPLE_SQL, LIFECYCLE_SQL
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.queries.lifecycle import LifecycleTrend


class ClickhouseLifecycle(LifecycleTrend):
    def get_interval(self, interval: str) -> Tuple[str, str]:
        if interval == "hour":
            return "1 HOUR", "HOUR"
        elif interval == "day":
            return "1 DAY", "DAY"
        elif interval == "week":
            return "1 WEEK", "WEEK"
        elif interval == "month":
            return "1 MONTH", "MONTH"
        else:
            raise ValidationError("{interval} not supported")

    def _format_lifecycle_query(self, entity: Entity, filter: Filter, team_id: int) -> Tuple[str, Dict, Callable]:
        date_from = filter.date_from

        if not date_from:
            date_from = get_earliest_timestamp(team_id)

        interval = filter.interval
        interval_string, interval_unit = self.get_interval(interval)
        _, _, date_params = parse_timestamps(filter=filter, team_id=team_id)

        event_query, event_params = LifecycleEventQuery(team_id=team_id, entity=entity, filter=filter).get_query()

        return (
            LIFECYCLE_SQL.format(
                interval=interval_string,
                interval_keyword=interval_unit,
                event_query=event_query,
                GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team_id),
            ),
            {"team_id": team_id, "interval": filter.interval, **event_params, **date_params,},
            self._parse_result(filter, entity),
        )

    def _parse_result(self, filter: Filter, entity: Entity) -> Callable:
        def _parse(result: List) -> List:
            res = []
            for val in result:
                label = "{} - {}".format(entity.name, val[2])
                additional_values = {"label": label, "status": val[2]}
                parsed_result = parse_response(val, filter, additional_values)
                res.append(parsed_result)

            return res

        return _parse

    def get_people(
        self,
        filter: Filter,
        team_id: int,
        target_date: datetime,
        lifecycle_type: str,
        request: Request,
        limit: int = 100,
    ):
        entity = filter.entities[0]
        date_from = filter.date_from

        if not date_from:
            date_from = get_earliest_timestamp(team_id)

        interval = filter.interval
        interval_string, interval_unit = self.get_interval(interval)
        _, _, date_params = parse_timestamps(filter=filter, team_id=team_id)

        event_query, event_params = LifecycleEventQuery(team_id=team_id, entity=entity, filter=filter).get_query()

        result = sync_execute(
            LIFECYCLE_PEOPLE_SQL.format(
                interval=interval_string,
                interval_keyword=interval_unit,
                event_query=event_query,
                GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team_id),
            ),
            {
                "team_id": team_id,
                "interval": filter.interval,
                **event_params,
                **date_params,
                "status": lifecycle_type,
                "target_date": target_date,
                "offset": filter.offset,
                "limit": limit,
            },
        )
        people = get_persons_by_uuids(team_id=team_id, uuids=[p[0] for p in result])
        people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data


class LifecycleEventQuery(TrendsEventQuery):
    def _get_date_filter(self):
        """
        To be able to check if an event is the first of it's kind by user, we
        need to query over all of time, not just in the requested timerange.

        NOTE: to be fast when using this query as a subquery in a JOIN on the
        right hand side with a self join, I'm relying on some optimization
        happening, otherwise this is going to cause potentially very large joins.
        """
        return "", {}

    def _determine_should_join_distinct_ids(self) -> None:
        """
        To be able to associate events with the previous or next event by the
        same user, we need to pull in the associated person_id, so we always
        join on distinct_ids to ensure we have this available
        """
        self._should_join_distinct_ids = True
