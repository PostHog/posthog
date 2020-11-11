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

        trunc_func = self._get_trunc_func_ch(period)
        final_query = self.final_query(trunc_func)
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

    def _get_trunc_func_ch(self, period: str) -> str:
        if period == "Hour":
            return PERIOD_TRUNC_HOUR
        elif period == "Week":
            return PERIOD_TRUNC_WEEK
        elif period == "Day":
            return PERIOD_TRUNC_DAY
        elif period == "Month":
            return PERIOD_TRUNC_MONTH
        else:
            raise ValueError(f"Period {period} is unsupported.")

    def person_query(self):
        person_distinct_id = Table("person_distinct_id")

        q = (
            Query.from_(person_distinct_id)
            .select(person_distinct_id.person_id, person_distinct_id.distinct_id)
            .where(person_distinct_id.team_id == PyformatParameter("team_id"))
        )
        return q

    def reference_query(self, trunc: str):
        events = Table("events").as_("e")
        person_query = self.person_query().as_("pdi")
        toDateTime = CustomFunction("toDateTime", ["date"])
        truncFunc = CustomFunction(trunc, ["date"])
        return (
            Query.from_(events)
            .join(person_query)
            .on(person_query.distinct_id == events.distinct_id)
            .select(truncFunc(events.timestamp).as_("event_date"), person_query.person_id.as_("person_id"),)
            .distinct()
            .where(toDateTime(events.timestamp) >= PyformatParameter("start_date"))
            .where(toDateTime(events.timestamp) <= PyformatParameter("end_date"))
            .where(events.team_id >= PyformatParameter("team_id"))
        )

    def event_query(self):
        events = Table("events").as_("e")
        person_query = self.person_query().as_("pdi")
        toDateTime = CustomFunction("toDateTime", ["date"])

        return (
            Query.from_(events)
            .join(person_query)
            .on(person_query.distinct_id == events.distinct_id)
            .select(events.timestamp.as_("event_date"), person_query.person_id.as_("person_id"),)
            .where(toDateTime(events.timestamp) >= PyformatParameter("start_date"))
            .where(toDateTime(events.timestamp) <= PyformatParameter("end_date"))
            .where(events.team_id >= PyformatParameter("team_id"))
        )

    def final_query(self, trunc: str):
        toDateTime = CustomFunction("toDateTime", ["date"])
        truncFunc = CustomFunction(trunc, ["date"])
        dateDiff = CustomFunction("datediff", ["period", "start_date", "end_date"])

        event_query = self.event_query().as_("event")
        reference_event = self.reference_query(trunc).as_("reference_event")

        final_query = (
            Query.from_(event_query)
            .join(reference_event)
            .on(event_query.person_id == reference_event.person_id)
            .select(
                dateDiff(
                    PyformatParameter("period"),
                    truncFunc(toDateTime(PyformatParameter("start_date"))),
                    reference_event.event_date,
                ).as_("period_to_event_days"),
                dateDiff(
                    PyformatParameter("period"),
                    reference_event.event_date,
                    truncFunc(toDateTime(event_query.event_date)),
                ).as_("period_between_events_days"),
                fn.Count(event_query.person_id).distinct().as_("count"),
            )
            .where(truncFunc(event_query.event_date) >= truncFunc(reference_event.event_date))
            .groupby(Field("period_to_event_days"), Field("period_between_events_days"))
        )

        return str(final_query)
