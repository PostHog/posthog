from .base import BaseTest
from posthog.models import Action, ActionStep, Event, Element, Person

class TestAction(BaseTest):
    TESTS_API = True

    def test_create_action(self): 
        user = self._create_user('tim')
        self.client.force_login(user)
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
        steps = action.steps.all()
        self.assertEqual(action.name, 'user signed up 2')
        self.assertEqual(steps[0].text, 'sign up NOW')
        self.assertEqual(steps[1].href, '/a-new-link')

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

