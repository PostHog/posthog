from .base import BaseTest
from posthog.models import Event, Person
import base64
import json


class TestCapture(BaseTest):
    TESTS_API = True

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode('utf-8')).decode('utf-8')


    def test_capture_new_person(self):
        user = self._create_user('tim')

        response = self.client.get('/e/?data=%s' % self._dict_to_b64({
            'event': '$web_event',
            'properties': {
                'distinct_id': 2,
                'token': self.team.api_token,
                '$elements': [
                    {'tag_name': 'a', 'nth_child': 1, 'nth_of_type': 2},
                    {'tag_name': 'div', 'nth_child': 1, 'nth_of_type': 2}
                ]
            },
        }), content_type='application/json', HTTP_REFERER='https://localhost')

        self.assertEqual(Person.objects.get().distinct_ids, ["2"])
        event = Event.objects.get()
        self.assertEqual(event.event, '$web_event')
        elements = event.element_set.all()
        self.assertEqual(elements[0].tag_name, 'a')
        self.assertEqual(elements[1].order, 1)
        self.assertEqual(event.properties['distinct_id'], "2")

    def test_capture_no_element(self):
        user = self._create_user('tim')

        response = self.client.get('/e/?data=%s' % self._dict_to_b64({
            'event': 'ph_page_view',
            'properties': {
                'distinct_id': 'asdfasdfasdf',
                'token': self.team.api_token,
            },
        }), content_type='application/json', HTTP_REFERER='https://localhost')

        self.assertEqual(Person.objects.get().distinct_ids, ["asdfasdfasdf"])
        event = Event.objects.get()
        self.assertEqual(event.event, 'ph_page_view')


    def test_engage(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        Person.objects.create(team=self.team, distinct_ids=["3", '455'])

        response = self.client.get('/engage/?data=%s' % self._dict_to_b64({
            '$set': {
                '$os': 'Mac OS X',
                '$browser': 'Chrome',
                '$browser_version': 79,
                '$initial_referrer': '$direct',
                '$initial_referring_domain': '$direct',
                'whatever': 'this is',
                'asdf': 'asdf'
            },
            '$token': 'token123',
            '$distinct_id': 3,
            '$device_id': '16fd4afae9b2d8-0fce8fe900d42b-39637c0e-7e9000-16fd4afae9c395',
            '$user_id': 3
        }), content_type='application/json', HTTP_REFERER='https://localhost')

        person = Person.objects.get()
        self.assertEqual(person.properties['whatever'], 'this is')