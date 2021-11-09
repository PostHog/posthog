from unittest.mock import patch
from uuid import uuid4

from django.utils import timezone

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.test.base import APIBaseTest

class ClickhouseTestGroupsApi(ClickhouseTestMixin, APIBaseTest):

    def test_property_values(self):
        response = self.client.get(f"/api/projects/{self.team.id}/groups/property_values").json()
        self.assertEqual(len(response["results"]), 1)
