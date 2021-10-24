from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_correlation_persons import FunnelCorrelationPersons
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models import Cohort, Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest, test_with_materialized_columns

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseFunnelCorrelationPersons(ClickhouseTestMixin, APIBaseTest):

    maxDiff = None

    def test_basic_funnel_correlation_with_events(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
        }

        filter = Filter(data=filters)

        success_target_persons = []
        failure_target_persons = []

        for i in range(10):
            person = _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
                success_target_persons.append(str(person.uuid))

            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            person = _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
                failure_target_persons.append(str(person.uuid))

        # One positively_related as failure
        person_fail = _create_person(distinct_ids=[f"user_fail"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id=f"user_fail", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="positively_related", distinct_id=f"user_fail", timestamp="2020-01-03T14:00:00Z",
        )

        # One negatively_related as success
        person_succ = _create_person(distinct_ids=[f"user_succ"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id=f"user_succ", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="negatively_related", distinct_id=f"user_succ", timestamp="2020-01-03T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id=f"user_succ", timestamp="2020-01-04T14:00:00Z",
        )

        # TESTS

        # test positively_related successes
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "positively_related", "type": "events"},
                "funnel_correlation_person_converted": "TrUe",
            }
        )
        results, has_more_results = FunnelCorrelationPersons(filter, self.team).run()

        self.assertFalse(has_more_results)
        self.assertCountEqual([val["uuid"] for val in results], success_target_persons)

        # test negatively_related failures
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "negatively_related", "type": "events"},
                "funnel_correlation_person_converted": "falsE",
            }
        )

        results, has_more_results = FunnelCorrelationPersons(filter, self.team).run()

        self.assertFalse(has_more_results)
        self.assertCountEqual([val["uuid"] for val in results], failure_target_persons)

        # test positively_related failures
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "positively_related", "type": "events"},
                "funnel_correlation_person_converted": "False",
            }
        )
        results, has_more_results = FunnelCorrelationPersons(filter, self.team).run()

        self.assertFalse(has_more_results)
        self.assertCountEqual([val["uuid"] for val in results], [str(person_fail.uuid)])

        # test negatively_related successes
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "negatively_related", "type": "events"},
                "funnel_correlation_person_converted": "trUE",
            }
        )
        results, has_more_results = FunnelCorrelationPersons(filter, self.team).run()

        self.assertFalse(has_more_results)
        self.assertCountEqual([val["uuid"] for val in results], [str(person_succ.uuid)])

        # test all positively_related
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "positively_related", "type": "events"},
                "funnel_correlation_person_converted": None,
            }
        )
        results, has_more_results = FunnelCorrelationPersons(filter, self.team).run()

        self.assertFalse(has_more_results)
        self.assertCountEqual([val["uuid"] for val in results], [*success_target_persons, str(person_fail.uuid)])

        # test all negatively_related
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "negatively_related", "type": "events"},
                "funnel_correlation_person_converted": None,
            }
        )
        results, has_more_results = FunnelCorrelationPersons(filter, self.team).run()

        self.assertFalse(has_more_results)
        self.assertCountEqual([val["uuid"] for val in results], [*failure_target_persons, str(person_succ.uuid)])

    def test_people_arent_returned_multiple_times(self):

        person = _create_person(distinct_ids=[f"user_1"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id=f"user_1", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="positively_related", distinct_id=f"user_1", timestamp="2020-01-03T14:00:00Z",
        )
        # duplicate event
        _create_event(
            team=self.team, event="positively_related", distinct_id=f"user_1", timestamp="2020-01-03T15:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id=f"user_1", timestamp="2020-01-04T14:00:00Z",
        )

        filter = Filter(
            data={
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
                "funnel_correlation_type": "events",
                "funnel_correlation_person_entity": {"id": "positively_related", "type": "events"},
                "funnel_correlation_person_converted": "TrUe",
            }
        )
        results, has_more_results = FunnelCorrelationPersons(filter, self.team).run()

        self.assertFalse(has_more_results)
        self.assertCountEqual([val["uuid"] for val in results], [str(person.uuid)])
