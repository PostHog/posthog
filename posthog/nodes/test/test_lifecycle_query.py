from freezegun import freeze_time

from posthog.models.utils import UUIDT
from posthog.nodes.lifecycle_query import run_lifecycle_query
from posthog.schema import LifecycleQuery
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_random_events(self) -> str:
        random_uuid = str(UUIDT())
        _create_person(
            properties={"sneaky_mail": "tim@posthog.com", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        flush_persons_and_events()
        for index in range(2):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "don't include", "random_uuid": random_uuid, "index": index},
            )
        flush_persons_and_events()
        return random_uuid

    def test_query(self):
        with freeze_time("2023-08-10"):
            self._create_random_events()
            response = run_lifecycle_query(
                query=LifecycleQuery.parse_obj(
                    {
                        "kind": "LifecycleQuery",
                        "dateRange": {"date_from": "-7d"},
                        "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "total"}],
                        "lifecycleFilter": {"shown_as": "Lifecycle"},
                        "interval": "day",
                    }
                ),
                team=self.team,
            )
            self.assertEqual(
                response,
                [
                    [
                        {
                            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "count": 0.0,
                            "labels": [
                                "2-Aug-2023",
                                "3-Aug-2023",
                                "4-Aug-2023",
                                "5-Aug-2023",
                                "6-Aug-2023",
                                "7-Aug-2023",
                                "8-Aug-2023",
                                "9-Aug-2023",
                            ],
                            "days": [
                                "2023-08-02",
                                "2023-08-03",
                                "2023-08-04",
                                "2023-08-05",
                                "2023-08-06",
                                "2023-08-07",
                                "2023-08-08",
                                "2023-08-09",
                            ],
                            "label": " - new",
                            "status": "new",
                        },
                        {
                            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "count": 0.0,
                            "labels": [
                                "2-Aug-2023",
                                "3-Aug-2023",
                                "4-Aug-2023",
                                "5-Aug-2023",
                                "6-Aug-2023",
                                "7-Aug-2023",
                                "8-Aug-2023",
                                "9-Aug-2023",
                            ],
                            "days": [
                                "2023-08-02",
                                "2023-08-03",
                                "2023-08-04",
                                "2023-08-05",
                                "2023-08-06",
                                "2023-08-07",
                                "2023-08-08",
                                "2023-08-09",
                            ],
                            "label": " - dormant",
                            "status": "dormant",
                        },
                        {
                            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "count": 0.0,
                            "labels": [
                                "2-Aug-2023",
                                "3-Aug-2023",
                                "4-Aug-2023",
                                "5-Aug-2023",
                                "6-Aug-2023",
                                "7-Aug-2023",
                                "8-Aug-2023",
                                "9-Aug-2023",
                            ],
                            "days": [
                                "2023-08-02",
                                "2023-08-03",
                                "2023-08-04",
                                "2023-08-05",
                                "2023-08-06",
                                "2023-08-07",
                                "2023-08-08",
                                "2023-08-09",
                            ],
                            "label": " - resurrecting",
                            "status": "resurrecting",
                        },
                        {
                            "data": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "count": 0.0,
                            "labels": [
                                "2-Aug-2023",
                                "3-Aug-2023",
                                "4-Aug-2023",
                                "5-Aug-2023",
                                "6-Aug-2023",
                                "7-Aug-2023",
                                "8-Aug-2023",
                                "9-Aug-2023",
                            ],
                            "days": [
                                "2023-08-02",
                                "2023-08-03",
                                "2023-08-04",
                                "2023-08-05",
                                "2023-08-06",
                                "2023-08-07",
                                "2023-08-08",
                                "2023-08-09",
                            ],
                            "label": " - returning",
                            "status": "returning",
                        },
                    ]
                ],
            )
