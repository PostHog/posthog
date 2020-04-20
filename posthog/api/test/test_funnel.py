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

        [action.calculate_events() for action in Action.objects.all()]

        response = self.client.post('/api/funnel/', data={
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
        funnels = Funnel.objects.get()
        self.assertEqual(funnels.filters['actions'][0]['id'], action_sign_up.pk) 
        self.assertEqual(funnels.filters['events'][0]['id'], 'user signed up') 
        self.assertEqual(funnels.get_steps()[0]['order'], 0)
        self.assertEqual(funnels.get_steps()[1]['order'], 1)

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

    def _signup_event(self, **kwargs):
        sign_up = Event.objects.create(team=self.team, event='user signed up', **kwargs)

    def _pay_event(self, **kwargs):
        sign_up = Event.objects.create(team=self.team, elements=[
            Element(tag_name='button', text='Pay $10')
        ], **kwargs)

    def _movie_event(self, **kwargs):
        sign_up = Event.objects.create(team=self.team, elements=[
            Element(tag_name='a', href='/movie')
        ], **kwargs)

    def _basic_funnel(self, properties=None):
        action_credit_card = Action.objects.create(team=self.team, name='paid')
        ActionStep.objects.create(action=action_credit_card, tag_name='button', text='Pay $10')
        action_play_movie = Action.objects.create(team=self.team, name='watched movie')
        ActionStep.objects.create(action=action_play_movie, tag_name='a', href='/movie')

        filters =  {
            'events': [
                {'id': 'user signed up', 'type': 'events', 'order': 0},
            ],
            'actions': [
                {'id': action_credit_card.pk, 'type': 'actions', 'order': 1},
                {'id': action_play_movie.pk, 'type': 'actions', 'order': 2},
            ]
        }

        if properties is not None:
            filters.update({
                'properties': properties
            })

        funnel = Funnel.objects.create(
            team=self.team,
            name='funnel',
            filters=filters
        )
        return funnel

    def test_funnel_events(self):
        funnel = self._basic_funnel()

        # events
        person_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup"], team=self.team)
        self._signup_event(distinct_id='stopped_after_signup')

        person_stopped_after_pay = Person.objects.create(distinct_ids=["stopped_after_pay"], team=self.team)
        self._signup_event(distinct_id='stopped_after_pay')
        self._pay_event(distinct_id='stopped_after_pay')

        person_stopped_after_movie = Person.objects.create(distinct_ids=["had_anonymous_id", "completed_movie"], team=self.team)
        self._signup_event(distinct_id='had_anonymous_id')
        self._pay_event(distinct_id='completed_movie')
        self._movie_event(distinct_id='completed_movie')

        person_that_just_did_movie = Person.objects.create(distinct_ids=["just_did_movie"], team=self.team)
        self._movie_event(distinct_id='just_did_movie')

        person_wrong_order = Person.objects.create(distinct_ids=["wrong_order"], team=self.team)
        self._pay_event(distinct_id='wrong_order')
        self._signup_event(distinct_id='wrong_order')
        self._movie_event(distinct_id='wrong_order')

        self._signup_event(distinct_id='a_user_that_got_deleted_or_doesnt_exist')

        with self.assertNumQueries(7):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        self.assertEqual(response['steps'][0]['name'], 'user signed up')
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
        self._signup_event(distinct_id='badalgo')
        with self.assertNumQueries(7):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

        self._pay_event(distinct_id='badalgo')
        with self.assertNumQueries(7):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

    def test_funnel_no_events(self):
        funnel = self._basic_funnel()

        with self.assertNumQueries(7):
            response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()

    def test_funnel_skipped_step(self):
        funnel = self._basic_funnel()

        person_wrong_order = Person.objects.create(distinct_ids=["wrong_order"], team=self.team)
        self._signup_event(distinct_id='wrong_order')
        self._movie_event(distinct_id='wrong_order')

        response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        self.assertEqual(response['steps'][1]['count'], 0)
        self.assertEqual(response['steps'][2]['count'], 0)

    def test_funnel_prop_filters(self):
        funnel = self._basic_funnel(properties={'$browser': 'Safari'})

        # events
        with_property = Person.objects.create(distinct_ids=["with_property"], team=self.team)
        self._signup_event(distinct_id='with_property', properties={'$browser': 'Safari'})
        self._pay_event(distinct_id='with_property', properties={'$browser': 'Safari'})

        # should not add a count
        without_property = Person.objects.create(distinct_ids=["without_property"], team=self.team)
        self._signup_event(distinct_id='without_property')
        self._pay_event(distinct_id='without_property', properties={'$browser': 'Safari'})

        # will add to first step
        half_property = Person.objects.create(distinct_ids=["half_property"], team=self.team)
        self._signup_event(distinct_id='half_property', properties={'$browser': 'Safari'})
        self._pay_event(distinct_id='half_property')

        response = self.client.get('/api/funnel/{}/'.format(funnel.pk)).json()
        self.assertEqual(response['steps'][0]['count'], 2)
        self.assertEqual(response['steps'][1]['count'], 1)