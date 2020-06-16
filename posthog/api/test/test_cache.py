from .base import BaseTest
from posthog.models import Action, ActionStep, Funnel
from django.core.cache import cache

class TestCache(BaseTest):
    TESTS_API = True

    def test_cached_funnel(self):
        action_sign_up = Action.objects.create(team=self.team, name='signed up')
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')
        action_credit_card = Action.objects.create(team=self.team, name='paid')
        ActionStep.objects.create(action=action_credit_card, tag_name='button', text='Pay $10')
        action_play_movie = Action.objects.create(team=self.team, name='watched movie')
        ActionStep.objects.create(action=action_play_movie, tag_name='a', href='/movie')
        Action.objects.create(team=self.team, name='user logged out')

        [action.calculate_events() for action in Action.objects.all()]

        self.client.post('/api/funnel/', data={
            'name': 'Whatever',
            'filters': {
                'events': [
                    {'id': 'user signed up', 'type': 'events', 'order': 0},
                ],
                'actions': [
                    {'id': action_sign_up.pk, 'type': 'actions', 'order': 1},
                ]
            }
        }, content_type='application/json').json()
        funnel = Funnel.objects.get()

        # no refresh after getting
        self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        original_name = cache.get('81047c15f602fb9e8716c8811809009c_Funnel')['result']['name']

        self.client.patch('/api/funnel/{}/'.format(funnel.pk), data={
            'name': 'Whatever2'
        }, content_type='application/json').json()

        self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        nonrefreshed_name = cache.get('81047c15f602fb9e8716c8811809009c_Funnel')['result']['name']  
        self.assertEqual(original_name, nonrefreshed_name)

        self.client.get('/api/funnel/{}/?refresh=true'.format(funnel.pk)).json()
        refreshed_name = cache.get('81047c15f602fb9e8716c8811809009c_Funnel')['result']['name']
        funnel = Funnel.objects.get()
        self.assertNotEqual(original_name, refreshed_name)
        self.assertEqual(funnel.name, refreshed_name)

