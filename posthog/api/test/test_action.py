from .base import BaseTest
from posthog.models import Action, ActionStep, Event, Element, Person
from freezegun import freeze_time # type: ignore
from urllib import parse
import json

def json_to_url(input) -> str:
    return parse.quote(json.dumps(input))

class TestAction(BaseTest):
    TESTS_API = True

    def test_create_and_update_action(self): 
        response = self.client.post('/api/action/', data={
            'name': 'user signed up',
            'steps': [{
                "text": "sign up",
                "selector": "div > button",
                "url": "/signup",
                "isNew": 'asdf'
            }]
        }, content_type='application/json', HTTP_ORIGIN='http://testserver').json()
        action = Action.objects.get()
        self.assertEqual(action.name, 'user signed up')
        self.assertEqual(action.team, self.team)
        self.assertEqual(action.steps.get().selector, 'div > button')
        self.assertEqual(response['steps'][0]['text'], 'sign up')

        # test no actions with same name
        user2 = self._create_user('tim2')
        self.client.force_login(user2)
        response = self.client.post('/api/action/', data={'name': 'user signed up'}, content_type='application/json', HTTP_ORIGIN='http://testserver').json()
        self.assertEqual(response['detail'], 'action-exists')

        # test update
        response = self.client.patch('/api/action/%s/' % action.pk, data={
            'name': 'user signed up 2',
            'steps': [{
                "id": action.steps.get().pk,
                "isNew": "asdf",
                "text": "sign up NOW",
                "selector": "div > button",
            }, {'href': '/a-new-link'}]
        }, content_type='application/json', HTTP_ORIGIN='http://testserver').json()
        action = Action.objects.get()
        steps = action.steps.all().order_by('id')
        self.assertEqual(action.name, 'user signed up 2')
        self.assertEqual(steps[0].text, 'sign up NOW')
        self.assertEqual(steps[1].href, '/a-new-link')

        # test queries
        with self.assertNumQueries(6):
            response = self.client.get('/api/action/')

        # test remove steps
        response = self.client.patch('/api/action/%s/' % action.pk, data={
            'name': 'user signed up 2',
            'steps': []
        }, content_type='application/json', HTTP_ORIGIN='http://testserver').json()
        self.assertEqual(ActionStep.objects.count(), 0)

    # When we send a user to their own site, we give them a token.
    # Make sure you can only create actions if that token is set,
    # otherwise evil sites could create actions with a users' session.
    # NOTE: Origin header is only set on cross domain request
    def test_create_from_other_domain(self):
        response = self.client.post('/api/action/', data={
            'name': 'user signed up',
        }, content_type='application/json', HTTP_ORIGIN='https://evilwebsite.com')
        self.assertEqual(response.status_code, 403)

        self.user.temporary_token = 'token123'
        self.user.save()

        response = self.client.post('/api/action/?temporary_token=token123', data={
            'name': 'user signed up',
        }, content_type='application/json', HTTP_ORIGIN='https://somewebsite.com')
        self.assertEqual(response.status_code, 200)

        list_response = self.client.get('/api/action/', content_type='application/json', HTTP_ORIGIN='https://evilwebsite.com')
        self.assertEqual(list_response.status_code, 403)

        detail_response = self.client.get('/api/action/{}/'.format(response.json()['id']), content_type='application/json', HTTP_ORIGIN='https://evilwebsite.com')
        self.assertEqual(detail_response.status_code, 403)

        self.client.logout()
        list_response = self.client.get('/api/action/?temporary_token=token123', content_type='application/json', HTTP_ORIGIN='https://somewebsite.com')
        self.assertEqual(list_response.status_code, 200)

        response = self.client.post('/api/action/?temporary_token=token123', data={
            'name': 'user signed up 22',
        }, content_type='application/json', HTTP_ORIGIN='https://somewebsite.com')
        self.assertEqual(response.status_code, 200, response.json())

    def test_trends_per_day(self):
        no_events = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=no_events, event='no events')

        sign_up_action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=sign_up_action, event='sign up')

        Person.objects.create(team=self.team, distinct_ids=['blabla'])

        with freeze_time('2019-12-24'):
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla', properties={"some_property": "value"})

        with freeze_time('2020-01-01'):
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla', properties={"some_property": "value"})
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla')
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla')
        with freeze_time('2020-01-02'):
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla', properties={"some_property": "other_value"})
            Event.objects.create(team=self.team, event='no events', distinct_id='blabla')

        with freeze_time('2020-01-04'):
            with self.assertNumQueries(7):
                response = self.client.get('/api/action/trends/').json()

        self.assertEqual(response[0]['labels'][4], 'Wed. 1 January')
        self.assertEqual(response[0]['data'][4], 3.0)
        self.assertEqual(response[0]['labels'][5], 'Thu. 2 January')
        self.assertEqual(response[0]['data'][5], 1.0)

        # test property filtering
        with freeze_time('2020-01-04'):
            response = self.client.get('/api/action/trends/?properties=%s' % json_to_url({'some_property': 'value'})).json()
        self.assertEqual(response[0]['labels'][4], 'Wed. 1 January')
        self.assertEqual(response[0]['data'][4], 1.0)
        self.assertEqual(response[0]['labels'][5], 'Thu. 2 January')
        self.assertEqual(response[0]['data'][5], 0)
        self.assertEqual(response[1]['count'], 0)

        # test day filtering
        with freeze_time('2020-01-02'):
            response = self.client.get('/api/action/trends/?date_from=2019-12-21').json()
        self.assertEqual(response[0]['labels'][3], 'Tue. 24 December')
        self.assertEqual(response[0]['data'][3], 1.0)
        self.assertEqual(response[0]['data'][12], 1.0)

        # test all filtering
        # automatically sets first day as first day of any events
        with freeze_time('2020-01-04'):
            response = self.client.get('/api/action/trends/?date_from=all').json()
        self.assertEqual(response[0]['labels'][0], 'Tue. 24 December')
        self.assertEqual(response[0]['data'][0], 1.0)

        # test breakdown filtering
        with freeze_time('2020-01-04'):
            response = self.client.get('/api/action/trends/?breakdown=some_property').json()

        self.assertEqual(response[0]['breakdown'][0]['name'], 'undefined')
        self.assertEqual(response[0]['breakdown'][0]['count'], 2)
        self.assertEqual(response[0]['breakdown'][1]['name'], 'other_value')
        self.assertEqual(response[0]['breakdown'][1]['count'], 1)
        self.assertEqual(response[0]['breakdown'][2]['name'], 'value')
        self.assertEqual(response[0]['breakdown'][2]['count'], 1)

        # test action filtering
        with freeze_time('2020-01-04'):
            response = self.client.get('/api/action/trends/?actions=%s' % json_to_url([{'id': sign_up_action.id}])).json()
        self.assertEqual(len(response), 1)

        # test DAU filtering
        with freeze_time('2020-01-02'):
            Event.objects.create(team=self.team, event='sign up', distinct_id='someone_else')
        with freeze_time('2020-01-04'):
            response = self.client.get('/api/action/trends/?actions=%s' % json_to_url([{'id': sign_up_action.id, 'math': 'dau'}])).json()
        self.assertEqual(response[0]['data'][4], 1)
        self.assertEqual(response[0]['data'][5], 2)