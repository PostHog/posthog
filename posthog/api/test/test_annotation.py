from .base import BaseTest
from posthog.models import Annotation, Dashboard, DashboardItem
from datetime import datetime
from freezegun import freeze_time

class TestAnnotation(BaseTest):
    TESTS_API = True

    def test_creating_and_retrieving_annotations(self):
        Annotation.objects.create(
            team=self.team, created_by=self.user, content="hello"
        )
        response = self.client.get('/api/annotation/').json()
        self.assertEqual(len(response['results']), 1)
        self.assertEqual(response['results'][0]['content'], "hello")

    def test_creating_and_retrieving_annotations_by_dashboard_item(self):

        dashboard = Dashboard.objects.create(name="Default", pinned=True, team=self.team)

        dashboardItem = DashboardItem.objects.create(
            team=self.team,
            dashboard=dashboard,
            name="Pageviews this week",
            last_refresh=datetime.now(),
        )
        Annotation.objects.create(
            team=self.team, created_by=self.user, content="hello", dashboard_item=dashboardItem
        )
        response = self.client.get('/api/annotation/?dashboard_item=1').json()

        self.assertEqual(len(response['results']), 1)
        self.assertEqual(response['results'][0]['content'], "hello")

    def test_query_annotations_by_datetime(self):

        Annotation.objects.create(
            team=self.team, created_by=self.user, content="hello_early", created_at="2020-01-04T13:00:01Z"
        )
        Annotation.objects.create(
            team=self.team, created_by=self.user, content="hello_later", created_at="2020-01-06T13:00:01Z"
        )
        response = self.client.get('/api/annotation/?before=2020-01-05').json()
        self.assertEqual(len(response['results']), 1)
        self.assertEqual(response['results'][0]['content'], "hello_early")

        response = self.client.get('/api/annotation/?after=2020-01-05').json()
        self.assertEqual(len(response['results']), 1)
        self.assertEqual(response['results'][0]['content'], "hello_later")
    
