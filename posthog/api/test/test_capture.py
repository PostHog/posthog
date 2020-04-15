from .base import BaseTest
from posthog.models import Event, Person, Team, User, ElementGroup, Action, ActionStep
from django.test import TransactionTestCase
from django.utils import timezone
from freezegun import freeze_time
from unittest.mock import patch, call
import base64
import json
import datetime
import pytz


class TestCapture(BaseTest):
    TESTS_API = True

    def _dict_to_json(self, data: dict) -> str:
        return json.dumps(data)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode('utf-8')).decode('utf-8')

    @patch('posthog.tasks.process_event.process_event.delay')
    def test_capture_new_person(self, patch_process_event):
        properties = {
            'distinct_id': 2,
            'token': self.team.api_token,
            '$elements': [
                {'tag_name': 'a', 'nth_child': 1, 'nth_of_type': 2, 'attr__class': 'btn btn-sm'},
                {'tag_name': 'div', 'nth_child': 1, 'nth_of_type': 2, '$el_text': '💻'}
            ]
        }
        now = timezone.now()
        with freeze_time(now):
            with self.assertNumQueries(1):
                response = self.client.get('/e/?data=%s' % self._dict_to_json({
                    'event': '$autocapture',
                    'properties': properties,
                }), content_type='application/json', HTTP_ORIGIN='https://localhost')
        self.assertEqual(response.get('access-control-allow-origin'), 'https://localhost')
        patch_process_event.assert_has_calls([call(
            ip='127.0.0.1',
            site_url='http://testserver',
            data=properties,
            event='$autocapture',
            team_id=self.team.pk,
            distinct_id=2,
            timestamp=now
        )])

    def test_multiple_events(self):
        response = self.client.post('/track/', data={
            'data': json.dumps([{
                'event': 'beep',
                'properties': {
                    'distinct_id': 'eeee',
                    'token': self.team.api_token,
                },
            },
                {
                'event': 'boop',
                'properties': {
                    'distinct_id': 'aaaa',
                    'token': self.team.api_token,
                },
            } ]),
            'api_key': self.team.api_token
        })

        events = Event.objects.all().count()
        self.assertEqual(events, 2)

    def test_emojis_in_text(self):
        self.team.api_token = 'xp9qT2VLY76JJg'
        self.team.save()
        response = self.client.post('/track/', data={
            'data': "eyJldmVudCI6ICIkd2ViX2V2ZW50IiwicHJvcGVydGllcyI6IHsiJG9zIjogIk1hYyBPUyBYIiwiJGJyb3dzZXIiOiAiQ2hyb21lIiwiJHJlZmVycmVyIjogImh0dHBzOi8vYXBwLmhpYmVybHkuY29tL2xvZ2luP25leHQ9LyIsIiRyZWZlcnJpbmdfZG9tYWluIjogImFwcC5oaWJlcmx5LmNvbSIsIiRjdXJyZW50X3VybCI6ICJodHRwczovL2FwcC5oaWJlcmx5LmNvbS8iLCIkYnJvd3Nlcl92ZXJzaW9uIjogNzksIiRzY3JlZW5faGVpZ2h0IjogMjE2MCwiJHNjcmVlbl93aWR0aCI6IDM4NDAsInBoX2xpYiI6ICJ3ZWIiLCIkbGliX3ZlcnNpb24iOiAiMi4zMy4xIiwiJGluc2VydF9pZCI6ICJnNGFoZXFtejVrY3AwZ2QyIiwidGltZSI6IDE1ODA0MTAzNjguMjY1LCJkaXN0aW5jdF9pZCI6IDYzLCIkZGV2aWNlX2lkIjogIjE2ZmQ1MmRkMDQ1NTMyLTA1YmNhOTRkOWI3OWFiLTM5NjM3YzBlLTFhZWFhMC0xNmZkNTJkZDA0NjQxZCIsIiRpbml0aWFsX3JlZmVycmVyIjogIiRkaXJlY3QiLCIkaW5pdGlhbF9yZWZlcnJpbmdfZG9tYWluIjogIiRkaXJlY3QiLCIkdXNlcl9pZCI6IDYzLCIkZXZlbnRfdHlwZSI6ICJjbGljayIsIiRjZV92ZXJzaW9uIjogMSwiJGhvc3QiOiAiYXBwLmhpYmVybHkuY29tIiwiJHBhdGhuYW1lIjogIi8iLCIkZWxlbWVudHMiOiBbCiAgICB7InRhZ19uYW1lIjogImJ1dHRvbiIsIiRlbF90ZXh0IjogIu2gve2yuyBXcml0aW5nIGNvZGUiLCJjbGFzc2VzIjogWwogICAgImJ0biIsCiAgICAiYnRuLXNlY29uZGFyeSIKXSwiYXR0cl9fY2xhc3MiOiAiYnRuIGJ0bi1zZWNvbmRhcnkiLCJhdHRyX19zdHlsZSI6ICJjdXJzb3I6IHBvaW50ZXI7IG1hcmdpbi1yaWdodDogOHB4OyBtYXJnaW4tYm90dG9tOiAxcmVtOyIsIm50aF9jaGlsZCI6IDIsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiZmVlZGJhY2stc3RlcCIsCiAgICAiZmVlZGJhY2stc3RlcC1zZWxlY3RlZCIKXSwiYXR0cl9fY2xhc3MiOiAiZmVlZGJhY2stc3RlcCBmZWVkYmFjay1zdGVwLXNlbGVjdGVkIiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJnaXZlLWZlZWRiYWNrIgpdLCJhdHRyX19jbGFzcyI6ICJnaXZlLWZlZWRiYWNrIiwiYXR0cl9fc3R5bGUiOiAid2lkdGg6IDkwJTsgbWFyZ2luOiAwcHggYXV0bzsgZm9udC1zaXplOiAxNXB4OyBwb3NpdGlvbjogcmVsYXRpdmU7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9fc3R5bGUiOiAib3ZlcmZsb3c6IGhpZGRlbjsiLCJudGhfY2hpbGQiOiAxLCJudGhfb2ZfdHlwZSI6IDF9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgIm1vZGFsLWJvZHkiCl0sImF0dHJfX2NsYXNzIjogIm1vZGFsLWJvZHkiLCJhdHRyX19zdHlsZSI6ICJmb250LXNpemU6IDE1cHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1jb250ZW50IgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1jb250ZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1kaWFsb2ciLAogICAgIm1vZGFsLWxnIgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1kaWFsb2cgbW9kYWwtbGciLCJhdHRyX19yb2xlIjogImRvY3VtZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbCIsCiAgICAiZmFkZSIsCiAgICAic2hvdyIKXSwiYXR0cl9fY2xhc3MiOiAibW9kYWwgZmFkZSBzaG93IiwiYXR0cl9fc3R5bGUiOiAiZGlzcGxheTogYmxvY2s7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJrLXBvcnRsZXRfX2JvZHkiLAogICAgIiIKXSwiYXR0cl9fY2xhc3MiOiAiay1wb3J0bGV0X19ib2R5ICIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDBweDsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgImstcG9ydGxldCIsCiAgICAiay1wb3J0bGV0LS1oZWlnaHQtZmx1aWQiCl0sImF0dHJfX2NsYXNzIjogImstcG9ydGxldCBrLXBvcnRsZXQtLWhlaWdodC1mbHVpZCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiY29sLWxnLTYiCl0sImF0dHJfX2NsYXNzIjogImNvbC1sZy02IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJyb3ciCl0sImF0dHJfX2NsYXNzIjogInJvdyIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDQwcHggMzBweCAwcHg7IGJhY2tncm91bmQtY29sb3I6IHJnYigyMzksIDIzOSwgMjQ1KTsgbWFyZ2luLXRvcDogLTQwcHg7IG1pbi1oZWlnaHQ6IGNhbGMoMTAwdmggLSA0MHB4KTsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJhdHRyX19zdHlsZSI6ICJtYXJnaW4tdG9wOiAwcHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJBcHAiCl0sImF0dHJfX2NsYXNzIjogIkFwcCIsImF0dHJfX3N0eWxlIjogImNvbG9yOiByZ2IoNTIsIDYxLCA2Mik7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9faWQiOiAicm9vdCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImJvZHkiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDF9Cl0sInRva2VuIjogInhwOXFUMlZMWTc2SkpnIn19"
        })

        self.assertEqual(Person.objects.get().distinct_ids, ["63"])
        event = Event.objects.get()
        element = ElementGroup.objects.get(hash=event.elements_hash).element_set.all().first()
        assert element is not None
        self.assertEqual(element.text, '💻 Writing code')

    def test_incorrect_padding(self):
        response = self.client.get('/e/?data=eyJldmVudCI6IndoYXRldmVmciIsInByb3BlcnRpZXMiOnsidG9rZW4iOiJ0b2tlbjEyMyIsImRpc3RpbmN0X2lkIjoiYXNkZiJ9fQ', content_type='application/json', HTTP_REFERER='https://localhost')
        self.assertEqual(response.json()['status'], 1)

    def test_ignore_empty_request(self):
        response = self.client.get('/e/?data=', content_type='application/json', HTTP_ORIGIN='https://localhost')
        self.assertEqual(response.content, b"1")


class TestBatch(BaseTest):
    TESTS_API = True
    def test_batch_capture(self):
        response = self.client.post('/batch/', data={
            'api_key': self.team.api_token,
            "batch":[
                {
                    "properties":{
                        "property1":"value",
                        "property2":"value",
                    },
                    "timestamp":"2020-02-10T01:45:20.777210+00:00",
                    "library": "posthog-python",
                    "library_version": "1.3.0b1",
                    "distinct_id":"test_id",
                    "type":"capture",
                    "event":"user signed up",
                    "messageId":"2b5c5750-46fc-4b21-8aa8-27032e8afb16"
                },
                {
                    "timestamp":"2020-02-10T01:46:20.777210+00:00",
                    "library": "posthog-python",
                    "library_version": "1.3.0b1",
                    "distinct_id":"test_id",
                    "type":"identify",
                    "$set": {
                        "email": "some@gmail.com"
                    },
                    "event":"$identify",
                    "messageId":"2b5c5750-46fc-4b21-8aa8-27032e8afb16",
                }
            ]
        }, content_type='application/json')

        events = Event.objects.all().order_by('id')
        self.assertEqual(events[0].event, 'user signed up')
        self.assertEqual(events[0].properties, {'property1': 'value', 'property2': 'value', '$ip': '127.0.0.1'})
        self.assertEqual(events[0].timestamp, datetime.datetime(2020, 2, 10, 1, 45, 20, 777210, tzinfo=pytz.UTC))
        self.assertEqual(events[1].event, '$identify')
        self.assertEqual(events[1].properties['email'], 'some@gmail.com')

        self.assertEqual(Person.objects.get(persondistinctid__distinct_id='test_id').distinct_ids, ['test_id'])
        self.assertEqual(Person.objects.get(persondistinctid__distinct_id='test_id').properties['email'], 'some@gmail.com')

    def test_batch_alias(self):
        Person.objects.create(team=self.team, distinct_ids=['old_distinct_id'])
        response = self.client.post('/batch/', data={
            "api_key": self.team.api_token,
            "batch":[{
                "properties":{
                    "distinct_id":"old_distinct_id",
                    "alias":"new_distinct_id"
                },
                "timestamp":"2020-02-10T01:45:20.777395+00:00",
                "library": "posthog-python",
                "version": "1.3.0b1",
                "type":"alias",
                "event":"$create_alias",
                "messageId":"7723c0fa-9801-497c-bf06-6d61e5572a84",
                "distinct_id": None,
            }]
        }, content_type='application/json')

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Person.objects.get().distinct_ids, ["old_distinct_id", "new_distinct_id"])

    def test_batch_engage(self):
        Person.objects.create(team=self.team, distinct_ids=["3", '455'])
        response = self.client.post('/batch/', data={
            "api_key": self.team.api_token,
            "batch": [{
                "timestamp":"2020-02-10T01:45:20.777635+00:00",
                "library": "posthog-python",
                "version":"1.3.0b1",
                "type":"identify",
                "distinct_id": "3",
                "$set":{
                    "email": "something@something.com"
                },
                "event":"$identify",
                "messageId":"90ac5fe7-713c-46fd-8552-5954baf478f6",
            }]
        }, content_type='application/json')

        person = Person.objects.get()
        self.assertEqual(person.properties['email'], 'something@something.com')

    def test_batch_engage_create_user(self):
        response = self.client.post('/batch/', data={
            "api_key": self.team.api_token,
            "batch": [{
                "timestamp":"2020-02-10T01:45:20.777635+00:00",
                "library": "posthog-python",
                "version":"1.3.0b1",
                "type":"identify",
                "distinct_id": "3",
                "$set":{
                    "email": "something@something.com"
                },
                "event":"$identify",
                "messageId":"90ac5fe7-713c-46fd-8552-5954baf478f6",
            }]
        }, content_type='application/json')

        person = Person.objects.get()
        self.assertEqual(person.properties['email'], 'something@something.com')

    def test_batch_incorrect_token(self):
        response = self.client.post('/batch/', data={
            "api_key": "this-token-doesnt-exist",
            "batch":[
                {
                    "type":"capture",
                    "event":"user signed up",
                    "distinct_id": "whatever"
                },
            ]
        }, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], "API key is incorrect. You can find your API key in the /setup page in PostHog.")

    def test_batch_token_not_set(self):
        response = self.client.post('/batch/', data={
            "batch":[
                {
                    "type":"capture",
                    "event":"user signed up",
                    "distinct_id": "whatever"
                },
            ]
        }, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], "No api_key set. You can find your API key in the /setup page in posthog")

    def test_batch_distinct_id_not_set(self):
        response = self.client.post('/batch/', data={
            "api_key": self.team.api_token,
            "batch":[
                {
                    "type":"capture",
                    "event":"user signed up",
                },
            ]
        }, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['message'], "You need to set a distinct_id.")

    def test_batch_offset(self):
        Person.objects.create(team=self.team, distinct_ids=['distinct_id'])
        with freeze_time("2020-01-01T12:00:05.200Z"):
            response = self.client.post('/batch/', data={
                "api_key": self.team.api_token,
                "batch":[{
                    "offset": 1500,
                    "event":"$autocapture",
                    "distinct_id": "distinct_id",
                },
                {
                    "offset": 150,
                    "event":"$autocapture",
                    "distinct_id": "distinct_id",
                }]
            }, content_type='application/json')

        events = Event.objects.all().order_by('timestamp')
        self.assertEqual(events[0].timestamp.isoformat(), '2020-01-01T12:00:03.700000+00:00')
        self.assertEqual(events[1].timestamp.isoformat(), '2020-01-01T12:00:05.050000+00:00')