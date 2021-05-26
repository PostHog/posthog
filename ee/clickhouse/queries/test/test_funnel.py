from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_funnel import ClickhouseFunnel
from ee.clickhouse.sql.funnels.funnel_trend import FUNNEL_TREND_SQL
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.person import Person
from posthog.queries.test.test_funnel import funnel_test_factory, funnel_trends_test_factory


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestFunnel(ClickhouseTestMixin, funnel_test_factory(ClickhouseFunnel, _create_event, _create_person)):  # type: ignore
    pass


class TestFunnelTrends(ClickhouseTestMixin, funnel_trends_test_factory(ClickhouseFunnel, _create_event, _create_person)):  # type: ignore
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

    def test_raw_query(self):
        # four people
        _create_person(distinct_ids=["query_one"], team=self.team)
        _create_person(distinct_ids=["query_two"], team=self.team)
        _create_person(distinct_ids=["query_three"], team=self.team)
        _create_person(distinct_ids=["query_four"], team=self.team)

        # query_one, funnel steps: one, two three
        _create_event(event="step one", distinct_id="query_one", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="query_one", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="query_one", team=self.team, timestamp="2021-05-05 00:00:00")

        # query_two, funnel steps: one, two
        _create_event(event="step one", distinct_id="query_two", team=self.team, timestamp="2021-05-02 00:00:00")
        _create_event(event="step two", distinct_id="query_two", team=self.team, timestamp="2021-05-04 00:00:00")

        # query_three, funnel steps: one
        _create_event(event="step one", distinct_id="query_three", team=self.team, timestamp="2021-05-06 00:00:00")

        # query_four, funnel steps: none
        _create_event(event="step none", distinct_id="query_four", team=self.team, timestamp="2021-05-06 00:00:00")

        query = FUNNEL_TREND_SQL.format(
            start_timestamp="2021-05-01 00:00:00", end_timestamp="2021-05-07 00:00:00", team_id=self.team.id,
        )

        results = sync_execute(query, {})
        users = self._convert_to_users(results)

        assert len(results) == 8
        assert len(users) == 4

        assert users["query_one"]["max_step"] == 3
        assert len(users["query_one"]["dates"]) == 3

        assert users["query_two"]["max_step"] == 2
        assert len(users["query_two"]["dates"]) == 2

        assert users["query_three"]["max_step"] == 1
        assert len(users["query_three"]["dates"]) == 1

        assert users["query_four"]["max_step"] == 0
        assert len(users["query_four"]["dates"]) == 1

    pass
