from django.test import TransactionTestCase
from django.utils.timezone import now
from freezegun import freeze_time
from posthog.api.test.base import BaseTest
from posthog.models import Event, Action, ActionStep, Person, ElementGroup, Team, User
from posthog.tasks.process_event import process_event
from unittest.mock import patch, call

class ProcessEvent(BaseTest):
    def test_capture_new_person(self):
        user = self._create_user('tim')
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, selector='a')
        action2 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action2, selector='a')

        with self.assertNumQueries(18):
            process_event(2, '', '', {
                'event': '$autocapture',
                'properties': {
                    'distinct_id': 2,
                    'token': self.team.api_token,
                    '$elements': [
                        {'tag_name': 'a', 'nth_child': 1, 'nth_of_type': 2, 'attr__class': 'btn btn-sm'},
                        {'tag_name': 'div', 'nth_child': 1, 'nth_of_type': 2, '$el_text': '💻'}
                    ]
                },
            }, self.team.pk, now().isoformat())

        self.assertEqual(Person.objects.get().distinct_ids, ["2"])
        event = Event.objects.get()
        self.assertEqual(event.event, '$autocapture')
        elements = ElementGroup.objects.get(hash=event.elements_hash).element_set.all().order_by('order')
        self.assertEqual(elements[0].tag_name, 'a')
        self.assertEqual(elements[0].attr_class, ['btn', 'btn-sm'])
        self.assertEqual(elements[1].order, 1)
        self.assertEqual(elements[1].text, '💻')
        self.assertEqual(event.distinct_id, "2")

    def test_capture_no_element(self):
        user = self._create_user('tim')
        Person.objects.create(team=self.team, distinct_ids=['asdfasdfasdf'])

        process_event('asdfasdfasdf', '', '', {
            'event': '$pageview',
            'properties': {
                'distinct_id': 'asdfasdfasdf',
                'token': self.team.api_token,
            },
        }, self.team.pk, now().isoformat())

        self.assertEqual(Person.objects.get().distinct_ids, ["asdfasdfasdf"])
        event = Event.objects.get()
        self.assertEqual(event.event, '$pageview')

    def test_alias(self):
        Person.objects.create(team=self.team, distinct_ids=['old_distinct_id'])

        process_event('new_distinct_id', '', '', {
            'event': '$create_alias',
            'properties': {
                'distinct_id': 'new_distinct_id',
                'token': self.team.api_token,
                'alias': 'old_distinct_id'
            },
        }, self.team.pk, now().isoformat())

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Person.objects.get().distinct_ids, ["old_distinct_id", "new_distinct_id"])

    def test_alias_twice(self):
        Person.objects.create(team=self.team, distinct_ids=['old_distinct_id'])

        process_event('new_distinct_id', '', '', {
            'event': '$create_alias',
            'properties': {
                'distinct_id': 'new_distinct_id',
                'token': self.team.api_token,
                'alias': 'old_distinct_id'
            },
        }, self.team.pk, now().isoformat())

        Person.objects.create(team=self.team, distinct_ids=['old_distinct_id_2'])

        process_event('new_distinct_id', '', '', {
            'event': '$create_alias',
            'properties': {
                'distinct_id': 'new_distinct_id',
                'token': self.team.api_token,
                'alias': 'old_distinct_id_2'
            },
        }, self.team.pk, now().isoformat())

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Person.objects.get().distinct_ids, ["old_distinct_id", "old_distinct_id_2", "new_distinct_id"])

    # This tends to happen when .init and .identify get called right after each other, causing a race condition
    # in this case the 'anonymous_id' won't have any actions anyway
    def test_alias_to_non_existent_distinct_id(self):
        process_event('new_distinct_id', '', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'doesnt_exist',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now().isoformat())

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Person.objects.get().distinct_ids, ['new_distinct_id'])

    def test_offset_timestamp(self):
        with freeze_time("2020-01-01T12:00:05.200Z"):
            process_event('distinct_id', '', '', {
                "offset": 150,
                "event":"$autocapture",
                "distinct_id": "distinct_id",
            }, self.team.pk, now().isoformat())

        event = Event.objects.get()
        self.assertEqual(event.timestamp.isoformat(), '2020-01-01T12:00:05.050000+00:00')

class TestIdentify(TransactionTestCase):
    def setUp(self, **kwargs) -> User:
        user: User = User.objects.create_user('tim@posthog.com', **kwargs)
        if not hasattr(self, 'team'):
            self.team: Team = Team.objects.create(api_token='token123')
        self.team.users.add(user)
        self.team.save()
        self.client.force_login(user)
        return user

    def test_distinct_with_anonymous_id(self):
        Person.objects.create(team=self.team, distinct_ids=['anonymous_id'])

        process_event('new_distinct_id', '', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'anonymous_id',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now().isoformat())

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Person.objects.get().distinct_ids, ["anonymous_id", "new_distinct_id"])

        # check no errors as this call can happen multiple times
        process_event('new_distinct_id', '', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'anonymous_id',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now().isoformat())

    # This case is likely to happen after signup, for example:
    # 1. User browses website with anonymous_id
    # 2. User signs up, triggers event with their new_distinct_id (creating a new Person)
    # 3. In the frontend, try to alias anonymous_id with new_distinct_id
    # Result should be that we end up with one Person with both ID's
    def test_distinct_with_anonymous_id_which_was_already_created(self):
        Person.objects.create(team=self.team, distinct_ids=['anonymous_id'])
        Person.objects.create(team=self.team, distinct_ids=['new_distinct_id'], properties={'email': 'someone@gmail.com'})

        process_event('new_distinct_id', '', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'anonymous_id',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now().isoformat())

        # self.assertEqual(Event.objects.count(), 0)
        person = Person.objects.get()
        self.assertEqual(person.distinct_ids, ["anonymous_id", "new_distinct_id"])
        self.assertEqual(person.properties['email'], 'someone@gmail.com')

    def test_distinct_with_multiple_anonymous_ids_which_were_already_created(self):
        # logging in the first time
        Person.objects.create(team=self.team, distinct_ids=['anonymous_id'])
        Person.objects.create(team=self.team, distinct_ids=['new_distinct_id'], properties={'email': 'someone@gmail.com'})

        process_event('new_distinct_id', '', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'anonymous_id',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now().isoformat())

        # self.assertEqual(Event.objects.count(), 0)
        person = Person.objects.get()
        self.assertEqual(person.distinct_ids, ["anonymous_id", "new_distinct_id"])
        self.assertEqual(person.properties['email'], 'someone@gmail.com')

        # logging in another time

        Person.objects.create(team=self.team, distinct_ids=['anonymous_id_2'])

        process_event('new_distinct_id', '', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'anonymous_id_2',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now().isoformat())

        person = Person.objects.get()
        self.assertEqual(person.distinct_ids, ["anonymous_id", "anonymous_id_2", "new_distinct_id"])
        self.assertEqual(person.properties['email'], 'someone@gmail.com')



    def test_distinct_team_leakage(self):
        team2 = Team.objects.create()
        Person.objects.create(team=team2, distinct_ids=['2'], properties={'email': 'team2@gmail.com'})
        Person.objects.create(team=self.team, distinct_ids=['1', '2'])

        try:
            process_event('2', '', '', {
                'event': '$identify',
                'properties': {
                    '$anon_distinct_id': '1',
                    'token': self.team.api_token,
                    'distinct_id': '2'
                },
            }, self.team.pk, now().isoformat())
        except:
            pass

        people = Person.objects.all()
        self.assertEqual(people.count(), 2)
        self.assertEqual(people[1].team, self.team)
        self.assertEqual(people[1].properties, {})
        self.assertEqual(people[1].distinct_ids, ["1", "2"])
        self.assertEqual(people[0].team, team2)
        self.assertEqual(people[0].distinct_ids, ["2"])