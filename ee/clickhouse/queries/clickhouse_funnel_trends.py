# [x] Move query logic to here
# [x] Get test framework working
# [x] Change assertions normal assertions
# [ ] Convert query results to interval (hours, partial days, days, weeks, months, years)
# [ ] Follow existing code patterns (Integrate filter class)
from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import get_trunc_func_ch, parse_timestamps
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
            "team_id": self._team.pk,
            "events": [],  # purely a speed optimization, don't need this for filtering
        }

    def run(self):
        query = self.configure_query()
        results = sync_execute(query, self.params)
        interval_results = self._transform_to_interval(results)
        return interval_results

    def configure_query(self):
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties,
            self._team.pk,
            prepend="global",
            allow_denormalized_props=True,
            filter_test_accounts=self._filter.filter_test_accounts,
        )
        parsed_date_from, parsed_date_to, _ = parse_timestamps(
            filter=self._filter, table="events.", team_id=self._team.pk
        )
        self.params.update(prop_filter_params)
        steps = [self._build_steps_query(entity, index) for index, entity in enumerate(self._filter.entities)]
        # TODO: determine within_time
        query = FUNNEL_TREND_SQL.format(
            team_id=self._team.id,
            steps=", ".join(steps),
            filters=prop_filters.replace("uuid IN", "events.uuid IN", 1),
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            within_time="86400000000",
            latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
            # top_level_groupby=", date",
            # extra_select="{}(timestamp) as date,".format(get_trunc_func_ch(self._filter.interval)),
            # extra_groupby=",{}(timestamp)".format(get_trunc_func_ch(self._filter.interval)),
        )
        return query

    @staticmethod
    def _transform_to_interval(self, results):
        return results

    @staticmethod
    def _run_query(format_dictionary):
        query = FUNNEL_TREND_SQL.format(**format_dictionary)
        results = sync_execute(query, {})
        return results

    @staticmethod
    def _milliseconds_from_days(days):
        second, minute, hour, day = [1000, 60, 60, 24]
        return second * minute * hour * day * days

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
