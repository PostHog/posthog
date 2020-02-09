from .base import BaseTest
from posthog.models import Event, Person
import base64
import json


class TestCapture(BaseTest):
    TESTS_API = True

    def _dict_to_json(self, data: dict) -> str:
        return json.dumps(data)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode('utf-8')).decode('utf-8')

    def test_capture_new_person(self):
        user = self._create_user('tim')

        response = self.client.get('/e/?data=%s' % self._dict_to_json({
            'event': '$autocapture',
            'properties': {
                'distinct_id': 2,
                'token': self.team.api_token,
                '$elements': [
                    {'tag_name': 'a', 'nth_child': 1, 'nth_of_type': 2, 'attr__class': 'btn btn-sm'},
                    {'tag_name': 'div', 'nth_child': 1, 'nth_of_type': 2, '$el_text': '💻'}
                ]
            },
        }), content_type='application/json', HTTP_REFERER='https://localhost')

        self.assertEqual(response._headers['access-control-allow-origin'][1], 'https://localhost')
        self.assertEqual(Person.objects.get().distinct_ids, ["2"])
        event = Event.objects.get()
        self.assertEqual(event.event, '$autocapture')
        elements = event.element_set.all().order_by('order')
        self.assertEqual(elements[0].tag_name, 'a')
        self.assertEqual(elements[0].attr_class, ['btn', 'btn-sm'])
        self.assertEqual(elements[1].order, 1)
        self.assertEqual(elements[1].text, '💻')
        self.assertEqual(event.properties['distinct_id'], "2")

    def test_capture_no_element(self):
        user = self._create_user('tim')
        Person.objects.create(team=self.team, distinct_ids=['asdfasdfasdf'])

        response = self.client.get('/e/?data=%s' % self._dict_to_json({
            'event': '$pageview',
            'properties': {
                'distinct_id': 'asdfasdfasdf',
                'token': self.team.api_token,
            },
        }), content_type='application/json', HTTP_REFERER='https://localhost')

        self.assertEqual(Person.objects.get().distinct_ids, ["asdfasdfasdf"])
        event = Event.objects.get()
        self.assertEqual(event.event, '$pageview')


    def test_engage(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        Person.objects.create(team=self.team, distinct_ids=["3", '455'])

        response = self.client.get('/engage/?data=%s' % self._dict_to_json({
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
        self.assertEqual(response._headers['access-control-allow-origin'][1], 'https://localhost')

        person = Person.objects.get()
        self.assertEqual(person.properties['whatever'], 'this is')

    def test_python_library(self):
        response = self.client.post('/track/', data={
            'data': self._dict_to_b64({
                'event': '$pageview',
                'properties': {
                    'distinct_id': 'eeee',
                    'token': self.team.api_token,
                },
            }),
            'api_key': self.team.api_token
        })

        self.assertEqual(Person.objects.get().distinct_ids, ["eeee"])
        event = Event.objects.get()
        self.assertEqual(event.event, '$pageview')

    def test_emojis_in_text(self):
        self.team.api_token = 'xp9qT2VLY76JJg'
        self.team.save()
        response = self.client.post('/track/', data={
            'data': "eyJldmVudCI6ICIkd2ViX2V2ZW50IiwicHJvcGVydGllcyI6IHsiJG9zIjogIk1hYyBPUyBYIiwiJGJyb3dzZXIiOiAiQ2hyb21lIiwiJHJlZmVycmVyIjogImh0dHBzOi8vYXBwLmhpYmVybHkuY29tL2xvZ2luP25leHQ9LyIsIiRyZWZlcnJpbmdfZG9tYWluIjogImFwcC5oaWJlcmx5LmNvbSIsIiRjdXJyZW50X3VybCI6ICJodHRwczovL2FwcC5oaWJlcmx5LmNvbS8iLCIkYnJvd3Nlcl92ZXJzaW9uIjogNzksIiRzY3JlZW5faGVpZ2h0IjogMjE2MCwiJHNjcmVlbl93aWR0aCI6IDM4NDAsInBoX2xpYiI6ICJ3ZWIiLCIkbGliX3ZlcnNpb24iOiAiMi4zMy4xIiwiJGluc2VydF9pZCI6ICJnNGFoZXFtejVrY3AwZ2QyIiwidGltZSI6IDE1ODA0MTAzNjguMjY1LCJkaXN0aW5jdF9pZCI6IDYzLCIkZGV2aWNlX2lkIjogIjE2ZmQ1MmRkMDQ1NTMyLTA1YmNhOTRkOWI3OWFiLTM5NjM3YzBlLTFhZWFhMC0xNmZkNTJkZDA0NjQxZCIsIiRpbml0aWFsX3JlZmVycmVyIjogIiRkaXJlY3QiLCIkaW5pdGlhbF9yZWZlcnJpbmdfZG9tYWluIjogIiRkaXJlY3QiLCIkdXNlcl9pZCI6IDYzLCIkZXZlbnRfdHlwZSI6ICJjbGljayIsIiRjZV92ZXJzaW9uIjogMSwiJGhvc3QiOiAiYXBwLmhpYmVybHkuY29tIiwiJHBhdGhuYW1lIjogIi8iLCIkZWxlbWVudHMiOiBbCiAgICB7InRhZ19uYW1lIjogImJ1dHRvbiIsIiRlbF90ZXh0IjogIu2gve2yuyBXcml0aW5nIGNvZGUiLCJjbGFzc2VzIjogWwogICAgImJ0biIsCiAgICAiYnRuLXNlY29uZGFyeSIKXSwiYXR0cl9fY2xhc3MiOiAiYnRuIGJ0bi1zZWNvbmRhcnkiLCJhdHRyX19zdHlsZSI6ICJjdXJzb3I6IHBvaW50ZXI7IG1hcmdpbi1yaWdodDogOHB4OyBtYXJnaW4tYm90dG9tOiAxcmVtOyIsIm50aF9jaGlsZCI6IDIsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiZmVlZGJhY2stc3RlcCIsCiAgICAiZmVlZGJhY2stc3RlcC1zZWxlY3RlZCIKXSwiYXR0cl9fY2xhc3MiOiAiZmVlZGJhY2stc3RlcCBmZWVkYmFjay1zdGVwLXNlbGVjdGVkIiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJnaXZlLWZlZWRiYWNrIgpdLCJhdHRyX19jbGFzcyI6ICJnaXZlLWZlZWRiYWNrIiwiYXR0cl9fc3R5bGUiOiAid2lkdGg6IDkwJTsgbWFyZ2luOiAwcHggYXV0bzsgZm9udC1zaXplOiAxNXB4OyBwb3NpdGlvbjogcmVsYXRpdmU7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9fc3R5bGUiOiAib3ZlcmZsb3c6IGhpZGRlbjsiLCJudGhfY2hpbGQiOiAxLCJudGhfb2ZfdHlwZSI6IDF9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgIm1vZGFsLWJvZHkiCl0sImF0dHJfX2NsYXNzIjogIm1vZGFsLWJvZHkiLCJhdHRyX19zdHlsZSI6ICJmb250LXNpemU6IDE1cHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1jb250ZW50IgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1jb250ZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1kaWFsb2ciLAogICAgIm1vZGFsLWxnIgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1kaWFsb2cgbW9kYWwtbGciLCJhdHRyX19yb2xlIjogImRvY3VtZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbCIsCiAgICAiZmFkZSIsCiAgICAic2hvdyIKXSwiYXR0cl9fY2xhc3MiOiAibW9kYWwgZmFkZSBzaG93IiwiYXR0cl9fc3R5bGUiOiAiZGlzcGxheTogYmxvY2s7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJrLXBvcnRsZXRfX2JvZHkiLAogICAgIiIKXSwiYXR0cl9fY2xhc3MiOiAiay1wb3J0bGV0X19ib2R5ICIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDBweDsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgImstcG9ydGxldCIsCiAgICAiay1wb3J0bGV0LS1oZWlnaHQtZmx1aWQiCl0sImF0dHJfX2NsYXNzIjogImstcG9ydGxldCBrLXBvcnRsZXQtLWhlaWdodC1mbHVpZCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiY29sLWxnLTYiCl0sImF0dHJfX2NsYXNzIjogImNvbC1sZy02IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJyb3ciCl0sImF0dHJfX2NsYXNzIjogInJvdyIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDQwcHggMzBweCAwcHg7IGJhY2tncm91bmQtY29sb3I6IHJnYigyMzksIDIzOSwgMjQ1KTsgbWFyZ2luLXRvcDogLTQwcHg7IG1pbi1oZWlnaHQ6IGNhbGMoMTAwdmggLSA0MHB4KTsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJhdHRyX19zdHlsZSI6ICJtYXJnaW4tdG9wOiAwcHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJBcHAiCl0sImF0dHJfX2NsYXNzIjogIkFwcCIsImF0dHJfX3N0eWxlIjogImNvbG9yOiByZ2IoNTIsIDYxLCA2Mik7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9faWQiOiAicm9vdCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImJvZHkiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDF9Cl0sInRva2VuIjogInhwOXFUMlZMWTc2SkpnIn19"
        })

        self.assertEqual(Person.objects.get().distinct_ids, ["63"])
        event = Event.objects.get()
        self.assertEqual(event.element_set.all().first().text, '💻 Writing code')

    def test_ignore_empty_request(self):
        response = self.client.get('/e/?data=', content_type='application/json', HTTP_REFERER='https://localhost')
        self.assertEqual(response.content, b"1")

    def test_alias(self):
        Person.objects.create(team=self.team, distinct_ids=['old_distinct_id'])

        response = self.client.get('/e/?data=%s' % self._dict_to_json({
            'event': '$create_alias',
            'properties': {
                'distinct_id': 'old_distinct_id',
                'token': self.team.api_token,
                'alias': 'new_distinct_id'
            },
        }), content_type='application/json', HTTP_REFERER='https://localhost')

        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(Person.objects.get().distinct_ids, ["old_distinct_id", "new_distinct_id"])
