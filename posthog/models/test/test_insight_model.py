from django.db.utils import IntegrityError

from posthog.models import Insight, Team
from posthog.test.base import BaseTest


class TestInsightModel(BaseTest):
    def test_short_id_and_team_must_be_unique_together(self):
        Insight.objects.create(team=self.team, short_id="123456")

        # The same ID could in theory be reused by another team
        new_team = Team.objects.create(organization=self.organization)
        Insight.objects.create(team=new_team, short_id="123456")

        count = Insight.objects.count()

        with self.assertRaises(IntegrityError):
            Insight.objects.create(team=self.team, short_id="123456")
            self.assertEqual(Insight.objects.count(), count)

    def test_short_id_is_automatically_generated(self):
        d = Insight.objects.create(team=self.team)
        self.assertRegex(d.short_id, r"[0-9A-Za-z_-]{8}")
