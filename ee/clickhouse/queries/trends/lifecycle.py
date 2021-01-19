from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.db.models.query import Prefetch

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.person import get_persons_by_distinct_ids, get_persons_by_uuids
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import parse_response
from ee.clickhouse.queries.util import get_earliest_timestamp, get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.trends.lifecycle import LIFECYCLE_PEOPLE_SQL, LIFECYCLE_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.queries.lifecycle import LifecycleTrend


class ClickhouseLifecycle(LifecycleTrend):
    def get_interval(self, interval: str) -> Tuple[Union[timedelta, relativedelta], str, str]:
        if interval == "hour":
            return timedelta(hours=1), "1 HOUR", "1 MINUTE"
        elif interval == "minute":
            return timedelta(minutes=1), "1 MINUTE", "1 SECOND"
        elif interval == "day":
            return timedelta(days=1), "1 DAY", "1 HOUR"
        elif interval == "week":
            return timedelta(weeks=1), "1 WEEK", "1 DAY"
        elif interval == "month":
            return relativedelta(months=1), "1 MONTH", "1 DAY"
        else:
            raise ValueError("{interval} not supported")

    def _serialize_lifecycle(self, entity: Entity, filter: Filter, team_id: int) -> List[Dict[str, Any]]:

        date_from = filter.date_from

        if not date_from:
            date_from = get_earliest_timestamp(team_id)

        interval = filter.interval or "day"
        num_intervals, seconds_in_interval, _ = get_time_diff(interval, filter.date_from, filter.date_to, team_id)
        interval_increment, interval_string, sub_interval_string = self.get_interval(interval)
        trunc_func = get_trunc_func_ch(interval)
        event_query = ""
        event_params: Dict[str, Any] = {}

        props_to_filter = [*filter.properties, *entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(props_to_filter, team_id)

        _, _, date_params = parse_timestamps(filter=filter, team_id=team_id)

        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                event_query, event_params = format_action_filter(action)
            except:
                return []
        else:
            event_query = "event = %(event)s"
            event_params = {"event": entity.id}

        result = sync_execute(
            LIFECYCLE_SQL.format(
                interval=interval_string,
                trunc_func=trunc_func,
                event_query=event_query,
                filters=prop_filters,
                sub_interval=sub_interval_string,
            ),
            {
                "team_id": team_id,
                "prev_date_from": (date_from - interval_increment).strftime(
                    "%Y-%m-%d{}".format(
                        " %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else " 00:00:00"
                    )
                ),
                "num_intervals": num_intervals,
                "seconds_in_interval": seconds_in_interval,
                **event_params,
                **date_params,
                **prop_filter_params,
            },
        )

        res = []
        for val in result:
            label = "{} - {}".format(entity.name, val[2])
            additional_values = {"label": label, "status": val[2]}
            parsed_result = parse_response(val, filter, additional_values)
            res.append(parsed_result)

        return res

    def get_people(
        self, filter: Filter, team_id: int, target_date: datetime, lifecycle_type: str, limit: int = 100,
    ):
        entity = filter.entities[0]
        date_from = filter.date_from

        if not date_from:
            date_from = get_earliest_timestamp(team_id)

        interval = filter.interval or "day"
        num_intervals, seconds_in_interval, _ = get_time_diff(
            interval, filter.date_from, filter.date_to, team_id=team_id
        )
        interval_increment, interval_string, sub_interval_string = self.get_interval(interval)
        trunc_func = get_trunc_func_ch(interval)
        event_query = ""
        event_params: Dict[str, Any] = {}

        _, _, date_params = parse_timestamps(filter=filter, team_id=team_id)

        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            try:
                action = Action.objects.get(pk=entity.id)
                event_query, event_params = format_action_filter(action)
            except:
                return []
        else:
            event_query = "event = %(event)s"
            event_params = {"event": entity.id}

        props_to_filter = [*filter.properties, *entity.properties]
        prop_filters, prop_filter_params = parse_prop_clauses(props_to_filter, team_id)

        result = sync_execute(
            LIFECYCLE_PEOPLE_SQL.format(
                interval=interval_string,
                trunc_func=trunc_func,
                event_query=event_query,
                filters=prop_filters,
                sub_interval=sub_interval_string,
            ),
            {
                "team_id": team_id,
                "prev_date_from": (date_from - interval_increment).strftime(
                    "%Y-%m-%d{}".format(
                        " %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else " 00:00:00"
                    )
                ),
                "num_intervals": num_intervals,
                "seconds_in_interval": seconds_in_interval,
                **event_params,
                **date_params,
                **prop_filter_params,
                "status": lifecycle_type,
                "target_date": target_date.strftime(
                    "%Y-%m-%d{}".format(
                        " %H:%M:%S" if filter.interval == "hour" or filter.interval == "minute" else " 00:00:00"
                    )
                ),
                "offset": filter.offset,
                "limit": limit,
            },
        )
        people = get_persons_by_uuids(team_id=team_id, uuids=[p[0] for p in result])
        people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data
