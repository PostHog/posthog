import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Match, Tuple

import pytz
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.funnels.funnel import FUNNEL_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TRENDS_LINEAR
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.queries.funnel import Funnel
from posthog.utils import format_label_date, get_daterange, relative_date_parse


class ClickhouseFunnel(Funnel):
    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team
        self.params = {
            "team_id": self._team.pk,
            "events": [],  # purely a speed optimization, don't need this for filtering
        }

    def _build_filters(self, entity: Entity, index: int) -> str:
        prop_filters, prop_filter_params = parse_prop_clauses(
            entity.properties, self._team.pk, prepend=str(index), allow_denormalized_props=True
        )
        self.params.update(prop_filter_params)
        if entity.properties:
            return prop_filters
        return ""

    def _build_steps_query(self, entity: Entity, index: int) -> str:
        filters = self._build_filters(entity, index)
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            for action_step in action.steps.all():
                self.params["events"].append(action_step.event)
            action_query, action_params = format_action_filter(action, "step_{}".format(index))
            if action_query == "":
                return ""

            self.params.update(action_params)
            content_sql = "{actions_query} {filters}".format(actions_query=action_query, filters=filters,)
        else:
            self.params["events"].append(entity.id)
            content_sql = "event = '{event}' {filters}".format(event=entity.id, filters=filters)
        return content_sql

    def _exec_query(self) -> List[Tuple]:
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties, self._team.pk, prepend="global", allow_denormalized_props=True
        )

        # format default dates
        data = {}
        if not self._filter._date_from:
            data.update({"date_from": relative_date_parse("-7d")})
        if not self._filter._date_to:
            data.update({"date_to": timezone.now()})
        self._filter = self._filter.with_data(data)

        parsed_date_from, parsed_date_to, _ = parse_timestamps(
            filter=self._filter, table="events.", team_id=self._team.pk
        )
        self.params.update(prop_filter_params)
        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        query = FUNNEL_SQL.format(
            team_id=self._team.id,
            steps=", ".join(steps),
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            top_level_groupby="",
            extra_select="",
            extra_groupby="",
            within_time="6048000000000000",
        )
        return sync_execute(query, self.params)

    def _get_trends(self) -> List[Dict[str, Any]]:
        serialized: Dict[str, Any] = {"count": 0, "data": [], "days": [], "labels": []}
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties, self._team.pk, prepend="global", allow_denormalized_props=True
        )
        parsed_date_from, parsed_date_to, _ = parse_timestamps(
            filter=self._filter, table="events.", team_id=self._team.pk
        )
        self.params.update(prop_filter_params)
        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        funnel_query = FUNNEL_SQL.format(
            team_id=self._team.id,
            steps=", ".join(steps),
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            top_level_groupby=", date",
            extra_select="{}(timestamp) as date,".format(get_trunc_func_ch(self._filter.interval)),
            extra_groupby=",{}(timestamp)".format(get_trunc_func_ch(self._filter.interval)),
            within_time="86400000000",
        )
        results = sync_execute(funnel_query, self.params)
        parsed_results = []

        for result in results:
            temp = [item for item in result]
            temp[1] = datetime(
                result[1].year,
                result[1].month,
                result[1].day,
                getattr(result[1], "hour", 0),
                getattr(result[1], "minute", 0),
                getattr(result[1], "second", 0),
                tzinfo=pytz.utc,
            )
            parsed_results.append(temp)

        date_range = get_daterange(
            self._filter.date_from or parsed_results[0][1], self._filter.date_to, frequency=self._filter.interval
        )

        # Rejig the data from a row for each date and step to one row per date
        data_dict: Dict[datetime, Dict] = {}
        for item in parsed_results:
            if not data_dict.get(item[1]):
                data_dict[item[1]] = {"date": item[1], "total_people": item[2], "count": 0}
            else:
                # the query gives people who made it to that step
                # so we need to count all the people from each step
                data_dict[item[1]]["total_people"] += item[2]
                data_dict[item[1]]["count"] = round(item[2] / data_dict[item[1]]["total_people"] * 100)
        data_array = [value for _, value in data_dict.items()]

        if self._filter.interval == "week":
            for df in data_array:
                df["date"] -= timedelta(days=df["date"].weekday() + 1)
        elif self._filter.interval == "month":
            for df in data_array:
                df["date"] = df["date"].replace(day=1)
        for df in data_array:
            df["date"] = df["date"].isoformat()

        datewise_data = {d["date"]: d["count"] for d in data_array}
        values = [(key, datewise_data.get(key.isoformat(), 0)) for key in date_range]

        for data_item in values:
            serialized["days"].append(data_item[0])
            serialized["data"].append(data_item[1])
            serialized["labels"].append(format_label_date(data_item[0], self._filter.interval))
        return [serialized]

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        if len(self._filter.entities) == 0:
            return []

        if self._filter.display == TRENDS_LINEAR:
            return self._get_trends()

        # Format of this is [step order, person count (that reached that step), array of person uuids]
        results = self._exec_query()

        steps = []
        relevant_people = []
        total_people = 0

        for step in reversed(self._filter.entities):
            # Clickhouse step order starts at one, hence the +1
            result_step = [x for x in results if step.order + 1 == x[0]]
            if len(result_step) > 0:
                total_people += result_step[0][1]
                relevant_people += result_step[0][2]
            steps.append(self._serialize_step(step, total_people, relevant_people[0:100]))

        return steps[::-1]  #  reverse
