from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_funnel import ClickhouseFunnel
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

        raw_sql = """
select date,
       count(*),
       groupArray(max_step),
       countIf(max_step > 0)
from (
    SELECT toDate(timestamp) as date,
           pid.person_id as id,
           windowFunnel(6048000000000000)(toUInt64(toUnixTimestamp64Micro(timestamp)), event = 'step one', event = 'step two', event = 'step three') as max_step
    FROM events
            JOIN (
       SELECT person_id,
              distinct_id
       FROM (
             SELECT *
             FROM person_distinct_id
                      JOIN (
                 SELECT distinct_id,
                        max(_offset) as _offset
                 FROM person_distinct_id
                 WHERE team_id = {team_id}
                 GROUP BY distinct_id
                 ) as person_max
                           ON person_distinct_id.distinct_id = person_max.distinct_id
                               AND person_distinct_id._offset = person_max._offset
             WHERE team_id = {team_id}
                )
       WHERE team_id = {team_id}
       ) as pid
                 ON pid.distinct_id = events.distinct_id
    WHERE team_id = {team_id}
     and events.timestamp >= '{start_timestamp}'
     and events.timestamp <= '{end_timestamp}'
     and event IN ['step one', 'step two', 'step three']
    GROUP BY pid.person_id, toDate(timestamp)
    order by toDate(timestamp) asc
)
group by date;
        """

        query = raw_sql.format(
            start_timestamp="2021-05-01 00:00:00", end_timestamp="2021-05-01 00:00:00", team_id=self.team.id,
        )

        response = sync_execute(query, {})
        assert len(response) > 0

    pass
