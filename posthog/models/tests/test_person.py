from ee.clickhouse.client import sync_execute
from posthog.models.person import Person
from posthog.test.base import BaseTest


class TestPerson(BaseTest):
    def test_create_and_send_to_clickhouse(self):
        Person.objects.create(
            send_to_clickhouse=True,
            send_to_clickhouse=True,
            send_to_clickhouse=True,
            team=self.team,
            properties={"test": "ok"},
        )
        self.assertEqual(
            1, sync_execute("select count(1) from person where team_id=%(team_id)s", {"team_id": self.team.pk})[0][0]
        )
