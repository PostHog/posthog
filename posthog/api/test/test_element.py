from .base import BaseTest
from posthog.models import Element, ElementGroup, Team

class TestElement(BaseTest):
    TESTS_API = True
    def test_event_property_values(self):
        group = ElementGroup.objects.create(team=self.team, elements=[
            Element(tag_name='a', href='https://posthog.com/about', text='click here')
        ])
        team2 = Team.objects.create()
        ElementGroup.objects.create(team=team2, elements=[
            Element(tag_name='bla')
        ])
        response = self.client.get('/api/element/values/?key=tag_name').json()
        self.assertEqual(response[0]['name'], 'a')
        self.assertEqual(len(response), 1)

        response = self.client.get('/api/element/values/?key=text&value=click').json()
        self.assertEqual(response[0]['name'], 'click here')
        self.assertEqual(len(response), 1)