from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.queries.test.test_retention import retention_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseRetention(ClickhouseTestMixin, retention_test_factory(ClickhouseRetention, _create_event, Person.objects.create)):  # type: ignore

    # period filtering for clickhouse only because start of week is different
    def test_retention_period(self):
        Person.objects.create(
            team=self.team, distinct_ids=["person1", "alias1"], properties={"email": "person1@test.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["person2"], properties={"email": "person2@test.com"},
        )

        self._create_pageviews(
            [
                ("person1", self._date(0)),
                ("person2", self._date(0)),
                ("person1", self._date(1)),
                ("person2", self._date(1)),
                ("person1", self._date(7)),
                ("person2", self._date(7)),
                ("person1", self._date(14)),
                ("person1", self._date(month=1, day=-6)),
                ("person2", self._date(month=1, day=-6)),
                ("person2", self._date(month=1, day=1)),
                ("person1", self._date(month=1, day=1)),
                ("person2", self._date(month=1, day=15)),
            ]
        )

        filter = Filter(data={"date_from": self._date(0, hour=0), "period": "Week"})

        result = ClickhouseRetention().run(filter, self.team, total_intervals=7)

        self.assertEqual(
            self.pluck(result, "values", "count"),
            [[2, 2, 1, 2, 2, 0, 1], [2, 1, 2, 2, 0, 1], [1, 1, 1, 0, 0], [2, 2, 0, 1], [2, 0, 1], [0, 0], [1],],
        )

        self.assertEqual(
            self.pluck(result, "date"),
            [
                "Sun. 7 June",
                "Sun. 14 June",
                "Sun. 21 June",
                "Sun. 28 June",
                "Sun. 5 July",
                "Sun. 12 July",
                "Sun. 19 July",
            ],
        )
