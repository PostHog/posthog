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
        }, content_type='application/json').json()
        action = Action.objects.get()
        self.assertEqual(action.name, 'user signed up')
        self.assertEqual(action.team, self.team)
        self.assertEqual(action.steps.get().selector, 'div > button')
        self.assertEqual(response['steps'][0]['text'], 'sign up')

        # test no actions with same name
        response = self.client.post('/api/action/', data={'name': 'user signed up'}, content_type='application/json').json()
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
        }, content_type='application/json').json()
        action = Action.objects.get()
        steps = action.steps.all()
        self.assertEqual(action.name, 'user signed up 2')
        self.assertEqual(steps[0].text, 'sign up NOW')
        self.assertEqual(steps[1].href, '/a-new-link')

        # test remove steps
        response = self.client.patch('/api/action/%s/' % action.pk, data={
            'name': 'user signed up 2',
            'steps': []
        }, content_type='application/json').json()
        self.assertEqual(ActionStep.objects.count(), 0)

