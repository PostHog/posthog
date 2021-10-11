from django.db.utils import IntegrityError

from posthog.models import DashboardItem, Team
from posthog.test.base import BaseTest


class TestDashboardItemModel(BaseTest):
    def test_short_id_and_team_must_be_unique_together(self):
        DashboardItem.objects.create(team=self.team, short_id="123456")

        # The same ID could in theory be reused by another team
        new_team = Team.objects.create(organization=self.organization)
        DashboardItem.objects.create(team=new_team, short_id="123456")

        count = DashboardItem.objects.count()

        with self.assertRaises(IntegrityError):
            DashboardItem.objects.create(team=self.team, short_id="123456")
            self.assertEqual(DashboardItem.objects.count(), count)

    def test_short_id_is_automatically_generated(self):
        d = DashboardItem.objects.create(team=self.team)
        self.assertRegex(d.short_id, r"[0-9A-Za-z_-]{8}")
