import datetime
from typing import Any, Dict, Tuple

import sqlparse
from pypika import CustomFunction, Field, PyformatParameter, Query, Table
from pypika import functions as fn

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.retention.retention import RETENTION_SQL
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.entity import Entity
from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.retention import Retention

PERIOD_TRUNC_HOUR = "toStartOfHour"
PERIOD_TRUNC_DAY = "toStartOfDay"
PERIOD_TRUNC_WEEK = "toStartOfWeek"
PERIOD_TRUNC_MONTH = "toStartOfMonth"


class ClickhouseRetention(Retention):
    person_distinct_id = Table("person_distinct_id")
    events = Table("events").as_("e")
    toDateTime = CustomFunction("toDateTime", ["date"])
    partFunc = lambda self, part, first_date, second_date: CustomFunction(
        "datediff", ["period", "start_date", "end_date"]
    )(part, second_date, first_date)

    def trunc_func(self, period: str, arg: Any) -> str:
        if period == "Hour":
            return CustomFunction(PERIOD_TRUNC_HOUR, ["date"])(arg)
        elif period == "Week":
            return CustomFunction(PERIOD_TRUNC_WEEK, ["date"])(arg)
        elif period == "Day":
            return CustomFunction(PERIOD_TRUNC_DAY, ["date"])(arg)
        elif period == "Month":
            return CustomFunction(PERIOD_TRUNC_MONTH, ["date"])(arg)
        else:
            raise ValueError(f"Period {period} is unsupported.")

    def _execute_sql(
        self,
        filter: Filter,
        date_from: datetime.datetime,
        date_to: datetime.datetime,
        target_entity: Entity,
        team: Team,
    ) -> Dict[Tuple[int, int], Dict[str, Any]]:
        period = filter.period
        prop_filters, prop_filter_params = parse_prop_clauses(filter.properties, team)

        target_query = ""
        target_params: Dict = {}

        if target_entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=target_entity.id)
            action_query, target_params = format_action_filter(action, use_loop=True)
            target_query = "AND e.uuid IN ({})".format(action_query)
        elif target_entity.type == TREND_FILTER_TYPE_EVENTS:
            target_query = "AND e.event = %(target_event)s"
            target_params = {"target_event": target_entity.id}

        final_query = self.final_query(period)
        print(sqlparse.format(str(final_query), reindent_aligned=True))
        result = sync_execute(
            final_query,
            {
                "team_id": team.pk,
                "start_date": date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                "end_date": date_to.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                **prop_filter_params,
                **target_params,
                "period": period,
            },
        )

        result_dict = {}

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        return result_dict

    def final_query(self, period: str):

        toDateTime = CustomFunction("toDateTime", ["date"])
        dateDiff = CustomFunction("datediff", ["period", "start_date", "end_date"])

        event_query = self.event_query().as_("event")
        reference_event = self.reference_query(period).as_("reference_event")

        final_query = (
            Query.from_(event_query)
            .join(reference_event)
            .on(event_query.person_id == reference_event.person_id)
            .select(
                dateDiff(
                    PyformatParameter("period"),
                    self.trunc_func(period, toDateTime(PyformatParameter("start_date"))),
                    reference_event.event_date,
                ).as_("period_to_event_days"),
                dateDiff(
                    PyformatParameter("period"),
                    reference_event.event_date,
                    self.trunc_func(period, toDateTime(event_query.event_date)),
                ).as_("period_between_events_days"),
                fn.Count(event_query.person_id).distinct().as_("count"),
            )
            .where(
                self.trunc_func(period, event_query.event_date) >= self.trunc_func(period, reference_event.event_date)
            )
            .groupby(Field("period_to_event_days"), Field("period_between_events_days"))
        )

        return str(final_query)
