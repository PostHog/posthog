from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.sql.events import NULL_SQL_FUNNEL_TRENDS
from ee.clickhouse.sql.funnels.funnel_trend import FUNNEL_TREND_SQL
from ee.clickhouse.sql.person import GET_LATEST_PERSON_DISTINCT_ID_SQL
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.queries.funnel import Funnel


class ClickhouseFunnelTrends(Funnel):
    _filter: Filter
    _team: Team

    def __init__(self, filter: Filter, team: Team):
        self._filter = filter
        self._team = team
        self.params = {
            "team_id": self._team.id,
            "events": [],  # purely a speed optimization, don't need this for filtering
        }

    def run(self):
        sql = self.configure_sql()
        results = sync_execute(sql, self.params)
        return results

    def configure_sql(self):
        funnel_trend_null_sql = self._get_funnel_trend_null_sql()
        parsed_date_from, parsed_date_to, _ = self._get_dates()
        prop_filters, prop_filter_params = self._get_filters()
        steps = self._get_steps()
        step_count = len(steps)
        interval_method = get_trunc_func_ch(self._filter.interval)

        sql = FUNNEL_TREND_SQL.format(
            team_id=self._team.pk,
            steps=", ".join(steps),
            step_count=step_count,
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            within_time=self._filter.funnel_window,
            latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
            funnel_trend_null_sql=funnel_trend_null_sql,
            interval_method=interval_method,
            # top_level_groupby=", date",
            # extra_select="{}(timestamp) as date,".format(get_trunc_func_ch(self._filter.interval)),
            # extra_groupby=",{}(timestamp)".format(get_trunc_func_ch(self._filter.interval)),
        )
        return sql

    def _get_funnel_trend_null_sql(self):
        interval_annotation = get_trunc_func_ch(self._filter.interval)
        num_intervals, seconds_in_interval, round_interval = get_time_diff(
            self._filter.interval or "day", self._filter.date_from, self._filter.date_to, team_id=self._team.id
        )
        funnel_trend_null_sql = NULL_SQL_FUNNEL_TRENDS.format(
            interval=interval_annotation,
            seconds_in_interval=seconds_in_interval,
            num_intervals=num_intervals,
            date_to=self._filter.date_to.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return funnel_trend_null_sql

    def _get_dates(self):
        return parse_timestamps(filter=self._filter, table="events.", team_id=self._team.pk)

    def _get_filters(self):
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties,
            self._team.pk,
            prepend="global",
            allow_denormalized_props=True,
            filter_test_accounts=self._filter.filter_test_accounts,
        )
        self.params.update(prop_filter_params)
        return prop_filters, prop_filter_params

    def _get_steps(self):
        return [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]

    @staticmethod
    def _run_query(format_dictionary):
        query = FUNNEL_TREND_SQL.format(**format_dictionary)
        results = sync_execute(query, {})
        return results

    @staticmethod
    def _convert_to_users(results):
        my_dict = dict()
        for index, value in enumerate(results):
            [date, distinct_id, max_step] = value
            if distinct_id in my_dict:
                my_dict[distinct_id]["dates"].append(date)
            elif distinct_id:
                my_dict[distinct_id] = {
                    "distinct_id": distinct_id,
                    "max_step": max_step,
                    "dates": [date],
                }
        return my_dict
