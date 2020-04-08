from .base import BaseTest
from posthog.models import Event, Person, Element, Action, ActionStep
from freezegun import freeze_time # type: ignore


class TestEvents(BaseTest):
    TESTS_API = True 
    ENDPOINT = 'event'

    def test_filter_events(self):
        person = Person.objects.create(properties={'email': 'tim@posthog.com'}, team=self.team, distinct_ids=["2", 'some-random-uid'])

        event1 = Event.objects.create(team=self.team, distinct_id="2", properties={"$ip": '8.8.8.8'}, elements=[
            Element(tag_name='button', text='something')
        ])
        Event.objects.create(team=self.team, distinct_id='some-random-uid', properties={"$ip": '8.8.8.8'})
        Event.objects.create(team=self.team, distinct_id='some-other-one', properties={"$ip": '8.8.8.8'})

        with self.assertNumQueries(10):
            response = self.client.get('/api/event/?distinct_id=2').json()
        self.assertEqual(response['results'][0]['person'], 'tim@posthog.com')
        self.assertEqual(response['results'][0]['elements'][0]['tag_name'], 'button')

    def test_filter_by_person(self):
        person = Person.objects.create(properties={'email': 'tim@posthog.com'}, distinct_ids=["2", 'some-random-uid'], team=self.team)

        Event.objects.create(team=self.team, distinct_id="2", properties={"$ip": '8.8.8.8'} )
        Event.objects.create(team=self.team, distinct_id='some-random-uid', properties={"$ip": '8.8.8.8'})
        Event.objects.create(team=self.team, distinct_id='some-other-one', properties={"$ip": '8.8.8.8'})

        response = self.client.get('/api/event/?person_id=%s' % person.pk).json()
        self.assertEqual(len(response['results']), 2)
        self.assertEqual(response['results'][0]['elements'], [])

    def _signup_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team, elements=[
            Element(tag_name='button', text='Sign up!')
        ])
        return sign_up

    def _pay_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team, elements=[
            Element(tag_name='button', text='Pay $10'),
            # check we're not duplicating
            Element(tag_name='div', text='Sign up!')
        ])
        return sign_up

    def _movie_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team, elements=[
            Element(tag_name='a', attr_class=['watch_movie', 'play'], text='Watch now', attr_id='something', href='/movie', order=0),
            Element(tag_name='div', href='/movie', order=1)
        ])

    def test_live_action_events(self):
        action_sign_up = Action.objects.create(team=self.team, name='signed up')
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')
        # 2 steps that match same element might trip stuff up
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')

        action_credit_card = Action.objects.create(team=self.team, name='paid')
        ActionStep.objects.create(action=action_credit_card, tag_name='button', text='Pay $10')

        action_watch_movie = Action.objects.create(team=self.team, name='watch movie')
        ActionStep.objects.create(action=action_watch_movie, text='Watch now', selector="div > a.watch_movie")

        # events
        person_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup"], team=self.team)
        event_sign_up_1 = self._signup_event('stopped_after_signup')

        person_stopped_after_pay = Person.objects.create(distinct_ids=["stopped_after_pay"], team=self.team)
        self._signup_event('stopped_after_pay')
        self._pay_event('stopped_after_pay')
        self._movie_event('stopped_after_pay')

        # Test filtering of deleted actions
        deleted_action_watch_movie = Action.objects.create(team=self.team, name='watch movie', deleted=True)
        ActionStep.objects.create(action=deleted_action_watch_movie, text='Watch now', selector="div > a.watch_movie")
        deleted_action_watch_movie.calculate_events()

        # non matching events
        non_matching = Event.objects.create(distinct_id='stopped_after_pay', properties={'$current_url': 'http://whatever.com'}, team=self.team, elements=[
            Element(tag_name='blabla', href='/moviedd', order=0),
            Element(tag_name='blabla', href='/moviedd', order=1)
        ])
        last_event = Event.objects.create(distinct_id='stopped_after_pay', properties={'$current_url': 'http://whatever.com'}, team=self.team)

        # with self.assertNumQueries(8):
        response = self.client.get('/api/event/actions/').json()
        self.assertEqual(len(response['results']), 4)
        self.assertEqual(response['results'][3]['event']['id'], event_sign_up_1.pk)
        self.assertEqual(response['results'][3]['action']['id'], action_sign_up.pk)
        self.assertEqual(response['results'][3]['action']['name'], 'signed up')

        self.assertEqual(response['results'][2]['action']['id'], action_sign_up.pk)
        self.assertEqual(response['results'][1]['action']['id'], action_credit_card.pk)

        self.assertEqual(response['results'][0]['action']['id'], action_watch_movie.pk)

        # test after
        sign_up_event = self._signup_event('stopped_after_pay')
        response = self.client.get('/api/event/actions/?after=%s' % last_event.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')).json()
        self.assertEqual(len(response['results']), 1)

    def test_event_names(self):
        Event.objects.create(team=self.team, event='user login')
        Event.objects.create(team=self.team, event='user sign up')
        Event.objects.create(team=self.team, event='user sign up')

        response = self.client.get('/api/event/names/').json()
        self.assertEqual(response[0]['name'], 'user login')
        self.assertEqual(response[1]['name'], 'user sign up')

    def test_event_property_names(self):
        Event.objects.create(team=self.team, properties={'$browser': 'whatever', '$os': 'Mac OS X'})
        Event.objects.create(team=self.team, properties={'random_prop': 'asdf'})
        Event.objects.create(team=self.team, properties={'random_prop': 'asdf'})

        response = self.client.get('/api/event/properties/').json()
        self.assertEqual(response[0]['name'], '$browser')
        self.assertEqual(response[1]['name'], '$os')
        self.assertEqual(response[2]['name'], 'random_prop')

    def test_event_property_values(self):
        Event.objects.create(team=self.team, properties={'random_prop': 'asdf', 'some other prop': 'with some text'})
        Event.objects.create(team=self.team, properties={'random_prop': 'asdf'})
        Event.objects.create(team=self.team, properties={'random_prop': 'qwerty'})
        Event.objects.create(team=self.team, properties={'something_else': 'qwerty'})
        response = self.client.get('/api/event/values/?key=random_prop').json()
        self.assertEqual(response[0]['name'], 'asdf')
        self.assertEqual(response[0]['count'], 2)
        self.assertEqual(response[1]['name'], 'qwerty')
        self.assertEqual(response[1]['count'], 1)

        response = self.client.get('/api/event/values/?key=random_prop&value=qw').json()
        self.assertEqual(response[0]['name'], 'qwerty')
        self.assertEqual(response[0]['count'], 1)

    def test_before_and_after(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        person = Person.objects.create(properties={'email': 'tim@posthog.com'}, team=self.team, distinct_ids=["2", 'some-random-uid'])

        with freeze_time("2020-01-10"):
            event1 = Event.objects.create(team=self.team, event='sign up', distinct_id="2")
        with freeze_time("2020-01-8"):
            event2 = Event.objects.create(team=self.team, event='sign up', distinct_id="2")

        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action, event='sign up')
        action.calculate_events()

        response = self.client.get('/api/event/?after=2020-01-09&action_id=%s' % action.pk).json()
        self.assertEqual(len(response['results']), 1)
        self.assertEqual(response['results'][0]['id'], event1.pk)

        response = self.client.get('/api/event/?before=2020-01-09&action_id=%s' % action.pk).json()
        self.assertEqual(len(response['results']), 1)
        self.assertEqual(response['results'][0]['id'], event2.pk)

        # without action
        response = self.client.get('/api/event/?after=2020-01-09').json()
        self.assertEqual(len(response['results']), 1)
        self.assertEqual(response['results'][0]['id'], event1.pk)
        
        response = self.client.get('/api/event/?before=2020-01-09').json()
        self.assertEqual(len(response['results']), 1)
        self.assertEqual(response['results'][0]['id'], event2.pk)