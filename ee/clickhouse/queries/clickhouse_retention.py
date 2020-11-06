from datetime import timedelta
from typing import Dict

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
from posthog.utils import SqlQuery, compose

PERIOD_TRUNC_HOUR = "toStartOfHour"
PERIOD_TRUNC_DAY = "toStartOfDay"
PERIOD_TRUNC_WEEK = "toStartOfWeek"
PERIOD_TRUNC_MONTH = "toStartOfMonth"


class ClickhouseRetention(Retention):
    def _get_trunc_func(self, period: str) -> str:
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

    def _execute_sql(self, filter: Filter, target_entity: Entity, team: Team):

        period = filter.period
        date_from = filter.date_from
        date_to = filter.date_to
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

        trunc_func = self._get_trunc_func(period)

        if period == "Week":
            date_from = date_from - timedelta(days=date_from.isoweekday() % 7)

        person_q = SqlQuery(
            SELECT="""
                person_id,
                distinct_id
            """,
            FROM="""
                person_distinct_id
            """,
            WHERE="""
                team_id = %(team_id)s
            """,
        ).update_params(team_id=team.pk)

        event_query = compose(
            lambda: SqlQuery(
                SELECT="""
                        timestamp AS event_date,
                        pdi.person_id as person_id
                        """.format(
                    trunc_func=trunc_func
                )
            )
            .c(
                WHERE="""
                        toDateTime(e.timestamp) >= toDateTime(%(start_date)s)
                        AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
                        AND e.team_id = %(team_id)s
                        """
            )
            .update_params(
                start_date=date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                end_date=date_to.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")),
                team_id=team.pk,
            )
            .c(FROM=f"events e JOIN ({person_q}) pdi on e.distinct_id = pdi.distinct_id")
            .update_params(**person_q.params),
            lambda q: target_query and q.c(WHERE=target_query).update_params(**target_params),
            lambda q: prop_filters and q.c(WHERE=prop_filters).update_params(**prop_filter_params),
        )

        reference_event_query = compose(
            lambda: SqlQuery(
                SELECT="""
                        DISTINCT pdi.person_id as person_id,
                        {trunc_func}(e.timestamp) as event_date
                        """.format(
                    trunc_func=trunc_func
                )
            )
            .c(
                WHERE="""
                        toDateTime(e.timestamp) >= toDateTime(%(start_date)s)
                        AND toDateTime(e.timestamp) <= toDateTime(%(end_date)s)
                        AND e.team_id = %(team_id)s
                        """
            )
            .update_params(
                start_date=date_from.strftime(
                    "%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")
                ),
                end_date=date_to.strftime("%Y-%m-%d{}".format(" %H:%M:%S" if filter.period == "Hour" else " 00:00:00")),
                team_id=team.pk,
            )
            .c(FROM=f"events e JOIN ({person_q}) pdi on e.distinct_id = pdi.distinct_id")
            .update_params(**person_q.params),
            lambda q: target_query and q.c(WHERE=target_query).update_params(**target_params),
            lambda q: prop_filters and q.c(WHERE=prop_filters).update_params(**prop_filter_params),
        )

        final_query = SqlQuery(
            SELECT="""
                datediff(%(period)s, {trunc_func}(toDateTime(%(start_date)s)), reference_event.event_date) as period_to_event_days,
                datediff(%(period)s, reference_event.event_date, {trunc_func}(toDateTime(event_date))) as period_between_events_days,
                COUNT(DISTINCT event.person_id) count
            """.format(
                trunc_func=trunc_func
            ),
            FROM=f"({event_query}) event JOIN ({reference_event_query}) reference_event ON (event.person_id = reference_event.person_id)",
            WHERE="{trunc_func}(event.event_date) >= {trunc_func}(reference_event.event_date)".format(
                trunc_func=trunc_func
            ),
            GROUP="period_to_event_days, period_between_events_days",
            ORDER="period_to_event_days, period_between_events_days",
        ).update_params(period=period, **reference_event_query.params)

        result = sync_execute(str(final_query), final_query.params)

        result_dict = {}

        for res in result:
            result_dict.update({(res[0], res[1]): {"count": res[2], "people": []}})

        return result_dict
