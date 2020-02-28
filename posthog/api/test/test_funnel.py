from posthog.models import Funnel, FunnelStep, Action, ActionStep, Event, Element, Person
from .base import BaseTest


class TestCreateFunnel(BaseTest):
    TESTS_API = True

    def test_create_funnel(self):
        action_sign_up = Action.objects.create(team=self.team, name='signed up')
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')
        action_credit_card = Action.objects.create(team=self.team, name='paid')
        ActionStep.objects.create(action=action_credit_card, tag_name='button', text='Pay $10')
        action_play_movie = Action.objects.create(team=self.team, name='watched movie')
        ActionStep.objects.create(action=action_play_movie, tag_name='a', href='/movie')
        action_logout = Action.objects.create(team=self.team, name='user logged out')

        response = self.client.post('/api/funnel/', data={
            'name': 'Whatever',
            'steps': [
                {'action_id': action_sign_up.pk},
                {'action_id': action_credit_card.pk},
                {}
            ]
        }, content_type='application/json').json()
        funnels = Funnel.objects.get()
        steps = funnels.steps.all()
        self.assertEqual(steps[0].action, action_sign_up) 
        self.assertEqual(steps[1].action, action_credit_card) 

        del response['steps'][1]
        response['steps'][0]['action_id'] = action_play_movie.pk
        response['steps'].append({'action_id': action_logout.pk, 'id': "8294bfc8-4a20-11ea-b77f-2e728ce8812"})
        response = self.client.patch('/api/funnel/%s/' % response['id'], data=response, content_type='application/json').json()
        funnels = Funnel.objects.get()
        steps = funnels.steps.all()
        self.assertEqual(steps[0].action, action_play_movie) 
        self.assertEqual(steps[1].action, action_logout) 
        self.assertEqual(len(steps), 2) 


        response['steps'] = []
        response = self.client.patch('/api/funnel/%s/' % response['id'], data=response, content_type='application/json').json()
        self.assertEqual(Funnel.objects.get().steps.count(), 0) 

    def test_delete_funnel(self):
        funnel = Funnel.objects.create(team=self.team)
        response = self.client.patch('/api/funnel/%s/' % funnel.pk, data={'deleted': True, 'steps': []}, content_type='application/json').json()
        response = self.client.get('/api/funnel/').json()
        self.assertEqual(len(response['results']), 0)

    # Autosaving in frontend means funnel without steps get created
    def test_create_and_update_funnel_no_steps(self):
        response = self.client.post('/api/funnel/', data={
            'name': 'Whatever'
        }, content_type='application/json').json()
        self.assertEqual(Funnel.objects.get().name, 'Whatever')

        response = self.client.patch('/api/funnel/%s/' % response['id'], data={
            'name': 'Whatever2'
        }, content_type='application/json').json()
        self.assertEqual(Funnel.objects.get().name, 'Whatever2')


class TestGetFunnel(BaseTest):
    TESTS_API = True

    def _signup_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team, elements=[
            Element(tag_name='button', text='Sign up!')
        ])

    def _pay_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team, elements=[
            Element(tag_name='button', text='Pay $10')
        ])

    def _movie_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team, elements=[
            Element(tag_name='a', href='/movie')
        ])

    def _basic_funnel(self):
        action_sign_up = Action.objects.create(team=self.team, name='signed up')
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')
        action_credit_card = Action.objects.create(team=self.team, name='paid')
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

        self._signup_event('a_user_that_got_deleted_or_doesnt_exist')

        with self.assertNumQueries(10):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        self.assertEqual(response['steps'][0]['name'], 'signed up')
        self.assertEqual(response['steps'][0]['count'], 4)
        # check ordering of people in first step
        self.assertEqual(response['steps'][0]['people'], [person_stopped_after_movie.pk, person_stopped_after_pay.pk, person_wrong_order.pk, person_stopped_after_signup.pk])
        self.assertEqual(response['steps'][1]['name'], 'paid')
        self.assertEqual(response['steps'][1]['count'], 2)
        self.assertEqual(response['steps'][2]['name'], 'watched movie')
        self.assertEqual(response['steps'][2]['count'], 1)
        self.assertEqual(response['steps'][2]['people'], [person_stopped_after_movie.pk])

        # make sure it's O(n)
        person_wrong_order = Person.objects.create(distinct_ids=["badalgo"], team=self.team)
        self._signup_event('badalgo')
        with self.assertNumQueries(10):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

        self._pay_event('badalgo')
        with self.assertNumQueries(10):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

    def test_funnel_no_events(self):
        funnel = self._basic_funnel()

        with self.assertNumQueries(10):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

    def test_funnel_skipped_step(self):
        funnel = self._basic_funnel()

        person_wrong_order = Person.objects.create(distinct_ids=["wrong_order"], team=self.team)
        self._signup_event('wrong_order')
        self._movie_event('wrong_order')

        response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        self.assertEqual(response['steps'][1]['count'], 0)
        self.assertEqual(response['steps'][2]['count'], 0)