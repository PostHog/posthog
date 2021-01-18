from uuid import uuid4

from django.test.utils import freeze_time

from posthog.models.event import Event
from posthog.models.filters.filter import Filter
from posthog.tasks.calculate_cohort import insert_cohort_from_query
from posthog.test.base import BaseTest


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    return Event(pk=_create_event(**kwargs))


class TestClickhouseCalculateCohort(BaseTest):
    def test_create_stickiness_cohort(self):
        pass

    def test_create_trends_cohort(self):
        with freeze_time("2020-01-01 00:06:34"):
            _create_event(
                team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 1},
            )

        with freeze_time("2020-01-02 00:06:34"):
            _create_event(
                team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 4},
            )

        Filter(
            data={"date_from": "-7d", "events": [{"id": "sign up"}, {"id": "no events"}],}
        )
