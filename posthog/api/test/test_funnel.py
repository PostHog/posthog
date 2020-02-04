from posthog.models import Funnel, FunnelStep, Action, ActionStep, Event, Element, Person
from .base import BaseTest


class TestCreateFunnel(BaseTest):
    TESTS_API = True

    def test_create_funnel(self):
        action_sign_up = Action.objects.create(team=self.team, name='signed up')
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')
        action_credit_card = Action.objects.create(team=self.team, name='payd')
        ActionStep.objects.create(action=action_credit_card, tag_name='button', text='Pay $10')
        action_play_movie = Action.objects.create(team=self.team, name='watched movie')
        ActionStep.objects.create(action=action_play_movie, tag_name='a', href='/movie')

        response = self.client.post('/api/funnel/', data={
            'name': 'Whatever',
            'steps': [
                {'action_id': action_sign_up.pk},
                {'action_id': action_credit_card.pk}
            ]
        }, content_type='application/json').json()
        funnels = Funnel.objects.get()
        steps = funnels.steps.all()
        self.assertEqual(steps[0].action, action_sign_up) 
        self.assertEqual(steps[1].action, action_credit_card) 


class TestGetFunnel(BaseTest):
    TESTS_API = True

    def _signup_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team)
        Element.objects.create(tag_name='button', text='Sign up!', event=sign_up)

    def _pay_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team)
        Element.objects.create(tag_name='button', text='Pay $10', event=sign_up)

    def _movie_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team)
        Element.objects.create(tag_name='a', href='/movie', event=sign_up)

    def _basic_funnel(self):
        action_sign_up = Action.objects.create(team=self.team, name='signed up')
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')
        action_credit_card = Action.objects.create(team=self.team, name='payd')
        ActionStep.objects.create(action=action_credit_card, tag_name='button', text='Pay $10')
        action_play_movie = Action.objects.create(team=self.team, name='watched movie')
        ActionStep.objects.create(action=action_play_movie, tag_name='a', href='/movie')

        funnel = Funnel.objects.create(team=self.team, name='funnel')
        FunnelStep.objects.create(funnel=funnel, order=0, action=action_sign_up)
        FunnelStep.objects.create(funnel=funnel, order=1, action=action_credit_card)
        FunnelStep.objects.create(funnel=funnel, order=2, action=action_play_movie)
        return funnel

    def test_funnel_events(self):
        funnel = self._basic_funnel()

        # events
        person_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup"], team=self.team)
        self._signup_event('stopped_after_signup')

        person_stopped_after_pay = Person.objects.create(distinct_ids=["stopped_after_pay"], team=self.team)
        self._signup_event('stopped_after_pay')
        self._pay_event('stopped_after_pay')

        person_stopped_after_movie = Person.objects.create(distinct_ids=["had_anonymous_id", "completed_movie"], team=self.team)
        self._signup_event('had_anonymous_id')
        self._pay_event('completed_movie')
        self._movie_event('completed_movie')

        person_that_just_did_movie = Person.objects.create(distinct_ids=["just_did_movie"], team=self.team)
        self._movie_event('just_did_movie')

        person_wrong_order = Person.objects.create(distinct_ids=["wrong_order"], team=self.team)
        self._pay_event('wrong_order')
        self._signup_event('wrong_order')
        self._movie_event('wrong_order')

        with self.assertNumQueries(14):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        self.assertEqual(response['steps'][0]['name'], 'signed up')
        self.assertEqual(response['steps'][0]['count'], 4)
        self.assertEqual(response['steps'][1]['name'], 'payd')
        self.assertEqual(response['steps'][1]['count'], 2)
        self.assertEqual(response['steps'][2]['name'], 'watched movie')
        self.assertEqual(response['steps'][2]['count'], 1)
        self.assertEqual(response['steps'][2]['people'], [person_stopped_after_movie.pk])

        # make sure it's O(n)
        person_wrong_order = Person.objects.create(distinct_ids=["badalgo"], team=self.team)
        self._signup_event('badalgo')
        with self.assertNumQueries(14):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

        self._pay_event('badalgo')
        with self.assertNumQueries(14):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

    def test_funnel_no_events(self):
        funnel = self._basic_funnel()

        with self.assertNumQueries(14):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

    def test_funnel_skipped_step(self):
        funnel = self._basic_funnel()

        person_wrong_order = Person.objects.create(distinct_ids=["wrong_order"], team=self.team)
        self._signup_event('wrong_order')
        self._movie_event('wrong_order')

        response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        self.assertEqual(response['steps'][1]['count'], 0)
        self.assertEqual(response['steps'][2]['count'], 0)