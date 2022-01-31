import json
import urllib.parse
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_correlation_persons import FunnelCorrelationActors
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models import Cohort, Filter
from posthog.models.person import Person
from posthog.tasks.calculate_cohort import insert_cohort_from_insight_filter
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


class TestClickhouseFunnelCorrelationActors(ClickhouseTestMixin, APIBaseTest):

    maxDiff = None

    def _setup_basic_test(self):
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
        events_by_person = {}
        for i in range(10):
            person_id = f"user_{i}"
            person = _create_person(distinct_ids=[person_id], team_id=self.team.pk)
            events_by_person[person_id] = [{"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)}]

            if i % 2 == 0:
                events_by_person[person_id].append(
                    {"event": "positively_related", "timestamp": datetime(2020, 1, 3, 14)}
                )

                success_target_persons.append(str(person.uuid))

            events_by_person[person_id].append({"event": "paid", "timestamp": datetime(2020, 1, 4, 14)})

        for i in range(10, 20):
            person_id = f"user_{i}"
            person = _create_person(distinct_ids=[person_id], team_id=self.team.pk)
            events_by_person[person_id] = [{"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)}]
            if i % 2 == 0:
                events_by_person[person_id].append(
                    {"event": "negatively_related", "timestamp": datetime(2020, 1, 3, 14)}
                )
                failure_target_persons.append(str(person.uuid))

        # One positively_related as failure
        person_fail_id = f"user_fail"
        person_fail = _create_person(distinct_ids=[person_fail_id], team_id=self.team.pk)
        events_by_person[person_fail_id] = [
            {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)},
            {"event": "positively_related", "timestamp": datetime(2020, 1, 3, 14)},
        ]

        # One negatively_related as success
        person_success_id = f"user_succ"
        person_succ = _create_person(distinct_ids=[person_success_id], team_id=self.team.pk)
        events_by_person[person_success_id] = [
            {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)},
            {"event": "negatively_related", "timestamp": datetime(2020, 1, 3, 14)},
            {"event": "paid", "timestamp": datetime(2020, 1, 4, 14)},
        ]
        journeys_for(events_by_person, self.team)

        return filter, success_target_persons, failure_target_persons, person_fail, person_succ

    def test_basic_funnel_correlation_with_events(self):
        filter, success_target_persons, failure_target_persons, person_fail, person_succ = self._setup_basic_test()

        # test positively_related successes
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "positively_related", "type": "events"},
                "funnel_correlation_person_converted": "TrUe",
            }
        )
        _, serialized_actors = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], success_target_persons)

        # test negatively_related failures
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "negatively_related", "type": "events"},
                "funnel_correlation_person_converted": "falsE",
            }
        )

        _, serialized_actors = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], failure_target_persons)

        # test positively_related failures
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "positively_related", "type": "events"},
                "funnel_correlation_person_converted": "False",
            }
        )
        _, serialized_actors = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], [str(person_fail.uuid)])

        # test negatively_related successes
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "negatively_related", "type": "events"},
                "funnel_correlation_person_converted": "trUE",
            }
        )
        _, serialized_actors = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], [str(person_succ.uuid)])

        # test all positively_related
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "positively_related", "type": "events"},
                "funnel_correlation_person_converted": None,
            }
        )
        _, serialized_actors = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual(
            [str(val["id"]) for val in serialized_actors], [*success_target_persons, str(person_fail.uuid)]
        )

        # test all negatively_related
        filter = filter.with_data(
            {
                "funnel_correlation_person_entity": {"id": "negatively_related", "type": "events"},
                "funnel_correlation_person_converted": None,
            }
        )
        _, serialized_actors = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual(
            [str(val["id"]) for val in serialized_actors], [*failure_target_persons, str(person_succ.uuid)]
        )

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_insight_filter.delay")
    def test_create_funnel_correlation_cohort(self, _insert_cohort_from_insight_filter):
        filter, success_target_persons, failure_target_persons, person_fail, person_succ = self._setup_basic_test()

        params = {
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

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/?{urllib.parse.urlencode(params)}",
            {"name": "test", "is_static": True},
        ).json()

        cohort_id = response["id"]

        _insert_cohort_from_insight_filter.assert_called_once_with(
            cohort_id,
            {
                "events": "[{'id': 'user signed up', 'type': 'events', 'order': 0}, {'id': 'paid', 'type': 'events', 'order': 1}]",
                "insight": "FUNNELS",
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
                "funnel_correlation_type": "events",
                "funnel_correlation_person_entity": "{'id': 'positively_related', 'type': 'events'}",
                "funnel_correlation_person_converted": "TrUe",
            },
        )

        insert_cohort_from_insight_filter(
            cohort_id, params,
        )

        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(len(people), 5)

    def test_people_arent_returned_multiple_times(self):

        people = journeys_for(
            {
                "user_1": [
                    {"event": "user signed up", "timestamp": datetime(2020, 1, 2, 14)},
                    {"event": "positively_related", "timestamp": datetime(2020, 1, 3, 14)},
                    # duplicate event
                    {"event": "positively_related", "timestamp": datetime(2020, 1, 3, 14)},
                    {"event": "paid", "timestamp": datetime(2020, 1, 4, 14)},
                ]
            },
            self.team,
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
        _, serialized_actors = FunnelCorrelationActors(filter, self.team).get_actors()

        self.assertCountEqual([str(val["id"]) for val in serialized_actors], [str(people["user_1"].uuid)])
