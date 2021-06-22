import json
import urllib.parse
from urllib.parse import urlencode

from rest_framework import status

from ee.clickhouse.generate_local import GenerateLocal
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_FUNNEL
from posthog.test.base import APIBaseTest


class TestFunnelPerson(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        GenerateLocal().generate()

    def test_basic_pagination(self):
        request_data = {
            "insight": INSIGHT_FUNNELS,
            "display": TRENDS_FUNNEL,
            "interval": "day",
            "actions": json.dumps([]),
            "events": json.dumps(
                [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}, {"id": "step three", "order": 2},]
            ),
            "properties": json.dumps([]),
            "funnel_window_days": 14,
            "filter_test_accounts": "false",
            "new_entity": json.dumps([]),
            "date_from": "2021-05-01",
            "date_to": "2021-05-10",
        }

        response = self.client.get("/api/person/funnel/", data=request_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(100, len(response.data))

        response = self.client.get("/api/person/funnel/", data={**request_data, "offset": 100})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(100, len(response.data))

        response = self.client.get("/api/person/funnel/", data={**request_data, "offset": 200})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(50, len(response.data))
