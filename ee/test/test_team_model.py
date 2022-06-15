from ee.clickhouse.models.group import create_group
from posthog.client import sync_execute
from posthog.models import Team
from posthog.models.team.util import delete_teams_clickhouse_data
from posthog.test.base import BaseTest, ClickhouseDestroyTablesMixin, ClickhouseTestMixin


class TestEnterpriseDeleteEvents(ClickhouseTestMixin, ClickhouseDestroyTablesMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.teams = [
            self.team,
            Team.objects.create(organization=self.organization),
            Team.objects.create(organization=self.organization),
        ]

    def test_delete_groups(self):
        create_group(self.teams[0].pk, 0, "g0")
        create_group(self.teams[1].pk, 1, "g1")
        create_group(self.teams[2].pk, 2, "g2")

        delete_teams_clickhouse_data([self.teams[0].pk, self.teams[1].pk])

        self.assertEqual(self.select_remaining("groups", "group_key"), ["g2"])

    def select_remaining(self, table, column):
        ids = [team.pk for team in self.teams]
        rows = sync_execute(f"SELECT {column} FROM {table} WHERE team_id IN %(ids)s", {"ids": ids})
        return [row[0] for row in rows]
