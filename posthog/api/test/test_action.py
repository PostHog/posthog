from json import dumps as jdumps

from freezegun import freeze_time

from posthog.models import Action, ActionStep, Element, Event, Person, Team
from .base import BaseTest


class TestCreateAction(BaseTest):
    TESTS_API = True

    def test_create_and_update_action(self):
        Event.objects.create(team=self.team, event='$autocapture', elements=[
            Element(tag_name='button', order=0, text='sign up NOW'),
            Element(tag_name='div', order=1),
        ])
        response = self.client.post('/api/action/', data={
            'name': 'user signed up',
            'steps': [{
                "text": "sign up",
                "selector": "div > button",
                "url": "/signup",
                "isNew": 'asdf',
            }],
        }, content_type='application/json', HTTP_ORIGIN='http://testserver').json()
        action = Action.objects.get()
        self.assertEqual(action.name, 'user signed up')
        self.assertEqual(action.team, self.team)
        self.assertEqual(action.steps.get().selector, 'div > button')
        self.assertEqual(response['steps'][0]['text'], 'sign up')

        # test no actions with same name
        user2 = self._create_user('tim2')
        self.client.force_login(user2)
        response = self.client.post(
            '/api/action/',
            data={'name': 'user signed up'},
            content_type='application/json',
            HTTP_ORIGIN='http://testserver',
        ).json()
        self.assertEqual(response['detail'], 'action-exists')

        # test update
        response = self.client.patch('/api/action/%s/' % action.pk, data={
            'name': 'user signed up 2',
            'steps': [{
                "id": action.steps.get().pk,
                "isNew": "asdf",
                "text": "sign up NOW",
                "selector": "div > button",
                "url": None,
            }, {'href': '/a-new-link'}],
        }, content_type='application/json', HTTP_ORIGIN='http://testserver').json()
        action = Action.objects.get()
        steps = action.steps.all().order_by('id')
        self.assertEqual(action.name, 'user signed up 2')
        self.assertEqual(steps[0].text, 'sign up NOW')
        self.assertEqual(steps[1].href, '/a-new-link')
        self.assertEqual(action.events.count(), 1)

        # test queries
        with self.assertNumQueries(5):
            response = self.client.get('/api/action/')

        # test remove steps
        response = self.client.patch('/api/action/%s/' % action.pk, data={
            'name': 'user signed up 2',
            'steps': [],
        }, content_type='application/json', HTTP_ORIGIN='http://testserver').json()
        self.assertEqual(ActionStep.objects.count(), 0)

    # When we send a user to their own site, we give them a token.
    # Make sure you can only create actions if that token is set,
    # otherwise evil sites could create actions with a users' session.
    # NOTE: Origin header is only set on cross domain request
    def test_create_from_other_domain(self):
        # FIXME: BaseTest is using Django client to performe calls to a DRF endpoint.
        # Django HttpResponse does not have an attribute `data`. Better use rest_framework.test.APIClient.
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

        response = self.client.post('/api/action/?temporary_token=token123', data={
            'name': 'user signed up and post to slack',
            'post_to_slack': True,
        }, content_type='application/json', HTTP_ORIGIN='https://somewebsite.com')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['post_to_slack'], True)

        list_response = self.client.get('/api/action/', content_type='application/json', HTTP_ORIGIN='https://evilwebsite.com')
        self.assertEqual(list_response.status_code, 403)

        detail_response = self.client.get(
            f"/api/action/{response.json()['id']}/",
            content_type='application/json',
            HTTP_ORIGIN='https://evilwebsite.com',
        )
        self.assertEqual(detail_response.status_code, 403)

        self.client.logout()
        list_response = self.client.get(
            '/api/action/',
            data={
                'temporary_token': 'token123',
            },
            content_type='application/json',
            HTTP_ORIGIN='https://somewebsite.com',
        )
        self.assertEqual(list_response.status_code, 200)

        response = self.client.post('/api/action/?temporary_token=token123', data={
            'name': 'user signed up 22',
        }, content_type='application/json', HTTP_ORIGIN='https://somewebsite.com')
        self.assertEqual(response.status_code, 200, response.json())


class TestTrends(BaseTest):
    TESTS_API = True

    def _create_events(self, use_time=False):
        no_events = Action.objects.create(team=self.team, name='no events')
        ActionStep.objects.create(action=no_events, event='no events')

        sign_up_action = Action.objects.create(team=self.team, name='sign up')
        ActionStep.objects.create(action=sign_up_action, event='sign up')

        person = Person.objects.create(team=self.team, distinct_ids=['blabla'])
        secondTeam = Team.objects.create(api_token='token123')

        freeze_without_time = ['2019-12-24', '2020-01-01', '2020-01-02']
        freeze_with_time = ['2019-12-24 03:45:34', '2020-01-01 00:06:34', '2020-01-02 16:34:34']

        freeze_args = freeze_without_time
        if use_time:
            freeze_args = freeze_with_time

        with freeze_time(freeze_args[0]):
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla', properties={"$some_property": "value"})

        with freeze_time(freeze_args[1]):
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla', properties={"$some_property": "value"})
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla')
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla')
        with freeze_time(freeze_args[2]):
            Event.objects.create(
                team=self.team,
                event='sign up',
                distinct_id='blabla',
                properties={"$some_property": "other_value"},
            )
            Event.objects.create(team=self.team, event='no events', distinct_id='blabla')

            # second team should have no effect
            Event.objects.create(
                team=secondTeam,
                event='sign up',
                distinct_id='blabla',
                properties={"$some_property": "other_value"},
            )
        return sign_up_action, person

    def _compare_entity_response(self, response1, response2, remove=('action', 'label')):
        if len(response1):
            for attr in remove:
                response1[0].pop(attr)
        else:
            return False
        if len(response2):
            for attr in remove:
                response2[0].pop(attr)
        else:
            return False
        return str(response1[0]) == str(response2[0])

    def test_trends_per_day(self):
        self._create_events()
        with freeze_time('2020-01-04T13:00:01Z'):
            with self.assertNumQueries(14):
                action_response = self.client.get('/api/action/trends/?date_from=-7d').json()
                event_response = self.client.get(
                    '/api/action/trends/',
                    data={
                        'date_from': '-7d',
                        'events': jdumps([{'id': "sign up"}, {'id': "no events"}]),
                    },
                ).json()

        self.assertEqual(action_response[0]['label'], 'sign up')
        self.assertEqual(action_response[0]['labels'][4], 'Wed. 1 January')
        self.assertEqual(action_response[0]['data'][4], 3.0)
        self.assertEqual(action_response[0]['labels'][5], 'Thu. 2 January')
        self.assertEqual(action_response[0]['data'][5], 1.0)
        self.assertEqual(event_response[0]['label'], 'sign up')

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_property_filtering(self):
        self._create_events()
        with freeze_time('2020-01-04'):
            action_response = self.client.get(
                '/api/action/trends/',
                data={
                    'properties': jdumps({'$some_property': 'value'}),
                },
            ).json()
            event_response = self.client.get(
                '/api/action/trends/',
                data={
                    'events': jdumps([{'id': "sign up"}, {'id': "no events"}]),
                    'properties': jdumps({'$some_property': 'value'}),
                },
            ).json()
        self.assertEqual(action_response[0]['labels'][4], 'Wed. 1 January')
        self.assertEqual(action_response[0]['data'][4], 1.0)
        self.assertEqual(action_response[0]['labels'][5], 'Thu. 2 January')
        self.assertEqual(action_response[0]['data'][5], 0)
        self.assertEqual(action_response[1]['count'], 0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_date_filtering(self):
        self._create_events()
        with freeze_time('2020-01-02'):
            action_response = self.client.get('/api/action/trends/?date_from=2019-12-21').json()
            event_response = self.client.get(
                '/api/action/trends/',
                data={
                    'date_from': '2019-12-21',
                    'events': jdumps([{'id': "sign up"}, {'id': "no events"}]),
                },
            ).json()
        self.assertEqual(action_response[0]['labels'][3], 'Tue. 24 December')
        self.assertEqual(action_response[0]['data'][3], 1.0)
        self.assertEqual(action_response[0]['data'][12], 1.0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_interval_filtering(self):
        self._create_events(use_time=True)

        # test minute
        with freeze_time('2020-01-02'):
            action_response = self.client.get('/api/action/trends/?date_from=2020-01-01&interval=minute').json()
        self.assertEqual(action_response[0]['labels'][6], 'Wed. 1 January, 00:06')
        self.assertEqual(action_response[0]['data'][6], 3.0)

        # test hour
        with freeze_time('2020-01-02'):
            action_response = self.client.get('/api/action/trends/?date_from=2019-12-24&interval=hour').json()
        self.assertEqual(action_response[0]['labels'][3], 'Tue. 24 December, 03:00')
        self.assertEqual(action_response[0]['data'][3], 1.0)
        # 217 - 24 - 1
        self.assertEqual(action_response[0]['data'][192], 3.0)

        # test week
        with freeze_time('2020-01-02'):
            action_response = self.client.get('/api/action/trends/?date_from=2019-11-24&interval=week').json()
        self.assertEqual(action_response[0]['labels'][4], 'Sun. 22 December')
        self.assertEqual(action_response[0]['data'][4], 1.0)
        self.assertEqual(action_response[0]['labels'][5], 'Sun. 29 December')
        self.assertEqual(action_response[0]['data'][5], 4.0)

        # test month
        with freeze_time('2020-01-02'):
            action_response = self.client.get('/api/action/trends/?date_from=2019-9-24&interval=month').json()
        self.assertEqual(action_response[0]['labels'][2], 'Sat. 30 November')
        self.assertEqual(action_response[0]['data'][2], 1.0)
        self.assertEqual(action_response[0]['labels'][3], 'Tue. 31 December')
        self.assertEqual(action_response[0]['data'][3], 4.0)

        with freeze_time('2020-01-02 23:30'):
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla')

        # test today + hourly
        with freeze_time('2020-01-02T23:31:00Z'):
            action_response = self.client.get(
                '/api/action/trends/',
                data={
                    'date_from': 'dStart',
                    'interval': 'hour',
                },
            ).json()
        self.assertEqual(action_response[0]['labels'][23], 'Thu. 2 January, 23:00')
        self.assertEqual(action_response[0]['data'][23], 1.0)

    def test_all_dates_filtering(self):
        self._create_events(use_time=True)
        # automatically sets first day as first day of any events
        with freeze_time('2020-01-04T15:01:01Z'):
            action_response = self.client.get('/api/action/trends/?date_from=all').json()
            event_response = self.client.get(
                '/api/action/trends/',
                data={
                    'date_from': 'all',
                    'events': jdumps([{'id': "sign up"}, {'id': "no events"}]),
                },
            ).json()
        self.assertEqual(action_response[0]['labels'][0], 'Tue. 24 December')
        self.assertEqual(action_response[0]['data'][0], 1.0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))


        # test empty response
        with freeze_time('2020-01-04'):
            empty = self.client.get('/api/action/trends/?date_from=all&events=%s' % jdumps([{'id': 'blabla'}, {'id': 'sign up'}])).json()
        self.assertEqual(empty[0]['data'][0], 0)

    def test_breakdown_filtering(self):
        self._create_events()
        # test breakdown filtering
        with freeze_time('2020-01-04T13:01:01Z'):
            action_response = self.client.get('/api/action/trends/?date_from=-14d&breakdown=$some_property').json()
            event_response = self.client.get('/api/action/trends/?date_from=-14d&properties={}&actions=[]&display=ActionsTable&interval=day&breakdown=$some_property&events=%s' % jdumps([{'id': "sign up", "name": "sign up", "type": "events", "order": 0}, {'id': "no events"}])).json()

        self.assertEqual(event_response[0]['label'], 'sign up - undefined')
        self.assertEqual(event_response[1]['label'], 'sign up - other_value')
        self.assertEqual(event_response[2]['label'], 'sign up - value')
        self.assertEqual(event_response[3]['label'], 'no events - undefined')

        self.assertEqual(sum(event_response[0]['data']), 2)
        self.assertEqual(event_response[0]['data'][4+7], 2)
        self.assertEqual(event_response[0]['breakdown_value'], None)

        self.assertEqual(sum(event_response[1]['data']), 1)
        self.assertEqual(event_response[1]['data'][5+7], 1)
        self.assertEqual(event_response[1]['breakdown_value'], 'other_value')

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_action_filtering(self):
        sign_up_action, person = self._create_events()
        with freeze_time('2020-01-04'):
            action_response = self.client.get(
                '/api/action/trends/',
                data={
                    'actions': jdumps([{'id': sign_up_action.id}]),
                },
            ).json()
            event_response = self.client.get(
                '/api/action/trends/',
                data={
                    'events': jdumps([{'id': "sign up"}]),
                },
            ).json()
        self.assertEqual(len(action_response), 1)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_trends_for_non_existing_action(self):
        with freeze_time('2020-01-04'):
            response = self.client.get('/api/action/trends/', {'actions': jdumps([{'id': 4000000}])}).json()
        self.assertEqual(len(response), 0)

        with freeze_time('2020-01-04'):
            response = self.client.get('/api/action/trends/', {'events': jdumps([{'id': "DNE"}])}).json()

        self.assertEqual(response[0]['data'], [0, 0, 0, 0, 0, 0, 0, 0])

    def test_dau_filtering(self):
        sign_up_action, person = self._create_events()
        with freeze_time('2020-01-02'):
            Event.objects.create(team=self.team, event='sign up', distinct_id='someone_else')
        with freeze_time('2020-01-04'):
            action_response = self.client.get(
                '/api/action/trends/',
                data={
                    'actions': jdumps([{'id': sign_up_action.id, 'math': 'dau'}]),
                },
            ).json()
            event_response = self.client.get(
                '/api/action/trends/',
                data={
                    'events': jdumps([{'id': "sign up", 'math': 'dau'}]),
                },
            ).json()
        self.assertEqual(action_response[0]['data'][4], 1)
        self.assertEqual(action_response[0]['data'][5], 2)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_dau_with_breakdown_filtering(self):
        sign_up_action, _ = self._create_events()
        with freeze_time('2020-01-02'):
            Event.objects.create(team=self.team, event='sign up', distinct_id='blabla', properties={"$some_property": "other_value"})
        with freeze_time('2020-01-04'):
            action_response = self.client.get('/api/action/trends/?breakdown=$some_property&actions=%s' % jdumps([{'id': sign_up_action.id, 'math': 'dau'}])).json()
            event_response = self.client.get('/api/action/trends/?breakdown=$some_property&events=%s' % jdumps([{'id': "sign up", 'math': 'dau'}])).json()

        self.assertEqual(event_response[0]['label'], 'sign up - other_value')
        self.assertEqual(event_response[1]['label'], 'sign up - value')
        self.assertEqual(event_response[2]['label'], 'sign up - undefined')

        self.assertEqual(sum(event_response[0]['data']), 1)
        self.assertEqual(event_response[0]['data'][5], 1)

        self.assertEqual(sum(event_response[2]['data']), 1)
        self.assertEqual(event_response[2]['data'][4], 1) # property not defined
 
        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_people_endpoint(self):
        sign_up_action, person = self._create_events()
        person1 = Person.objects.create(team=self.team, distinct_ids=['person1'])
        Person.objects.create(team=self.team, distinct_ids=['person2'])
        Event.objects.create(team=self.team, event='sign up', distinct_id='person1', timestamp='2020-01-04T12:00:00Z')
        Event.objects.create(team=self.team, event='sign up', distinct_id='person2', timestamp='2020-01-05T12:00:00Z')
        # test people
        action_response = self.client.get(
            '/api/action/people/',
            data={
                'date_from': '2020-01-04',
                'date_to': '2020-01-04',
                'type': 'actions',
                'entityId': sign_up_action.id,
            },
        ).json()
        event_response = self.client.get(
            '/api/action/people/',
            data={
                'date_from': '2020-01-04',
                'date_to': '2020-01-04',
                'type': 'events',
                'entityId': 'sign up',
            },
        ).json()

        self.assertEqual(action_response[0]['people'][0]['id'], person1.pk)
        self.assertTrue(self._compare_entity_response(action_response, event_response, remove=[]))

    def test_people_endpoint_with_intervals(self):
        sign_up_action, person = self._create_events()

        person1 = Person.objects.create(team=self.team, distinct_ids=['person1'])
        person2 = Person.objects.create(team=self.team, distinct_ids=['person2'])
        person3 = Person.objects.create(team=self.team, distinct_ids=['person3'])
        person4 = Person.objects.create(team=self.team, distinct_ids=['person4'])
        person5 = Person.objects.create(team=self.team, distinct_ids=['person5'])
        person6 = Person.objects.create(team=self.team, distinct_ids=['person6'])
        person7 = Person.objects.create(team=self.team, distinct_ids=['person7'])

        # solo
        Event.objects.create(team=self.team, event='sign up', distinct_id='person1', timestamp='2020-01-04T14:10:00Z')
        # group by hour
        Event.objects.create(team=self.team, event='sign up', distinct_id='person2', timestamp='2020-01-04T16:30:00Z')
        # group by hour
        Event.objects.create(team=self.team, event='sign up', distinct_id='person3', timestamp='2020-01-04T16:50:00Z')
        # group by min
        Event.objects.create(team=self.team, event='sign up', distinct_id='person4', timestamp='2020-01-04T19:20:00Z')
        # group by min
        Event.objects.create(team=self.team, event='sign up', distinct_id='person5', timestamp='2020-01-04T19:20:00Z')
        # group by week and month
        Event.objects.create(team=self.team, event='sign up', distinct_id='person6', timestamp='2019-11-05T16:30:00Z')
        # group by week and month
        Event.objects.create(team=self.team, event='sign up', distinct_id='person7', timestamp='2019-11-07T16:50:00Z')

        # check solo hour
        action_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'hour',
                'date_from': '2020-01-04 14:00:00',
                'date_to': '2020-01-04 14:00:00',
                'type': 'actions',
                'entityId': sign_up_action.id,
            },
        ).json()
        event_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'hour',
                'date_from': '2020-01-04 14:00:00',
                'date_to': '2020-01-04 14:00:00',
                'type': 'events',
                'entityId': 'sign up',
            },
        ).json()
        self.assertEqual(action_response[0]['people'][0]['id'], person1.pk)
        self.assertEqual(len(action_response[0]['people']), 1)
        self.assertTrue(self._compare_entity_response(action_response, event_response, remove=[]))

        # check grouped hour
        hour_grouped_action_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'hour',
                'date_from': '2020-01-04 16:00:00',
                'date_to': '2020-01-04 16:00:00',
                'type': 'actions',
                'entityId': sign_up_action.id,
            },
        ).json()
        hour_grouped_grevent_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'hour',
                'date_from': '2020-01-04 16:00:00',
                'date_to': '2020-01-04 16:00:00',
                'type': 'events',
                'entityId': 'sign up',
            },
        ).json()
        self.assertEqual(hour_grouped_action_response[0]['people'][0]['id'], person2.pk)
        self.assertEqual(hour_grouped_action_response[0]['people'][1]['id'], person3.pk)
        self.assertEqual(len(hour_grouped_action_response[0]['people']), 2)
        self.assertTrue(self._compare_entity_response(
            hour_grouped_action_response,
            hour_grouped_grevent_response,
            remove=[],
        ))

        # check grouped minute
        min_grouped_action_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'hour',
                'date_from': '2020-01-04 19:20:00',
                'date_to': '2020-01-04 19:20:00',
                'type': 'actions',
                'entityId': sign_up_action.id,
            },
        ).json()
        min_grouped_grevent_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'hour',
                'date_from': '2020-01-04 19:20:00',
                'date_to': '2020-01-04 19:20:00',
                'type': 'events',
                'entityId': 'sign up',
            },
        ).json()
        self.assertEqual(min_grouped_action_response[0]['people'][0]['id'], person4.pk)
        self.assertEqual(min_grouped_action_response[0]['people'][1]['id'], person5.pk)
        self.assertEqual(len(min_grouped_action_response[0]['people']), 2)
        self.assertTrue(self._compare_entity_response(
            min_grouped_action_response,
            min_grouped_grevent_response,
            remove=[],
        ))

        # check grouped week
        week_grouped_action_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'week',
                'date_from': '2019-11-01',
                'date_to': '2019-11-01',
                'type': 'actions',
                'entityId': sign_up_action.id,
            },
        ).json()
        week_grouped_grevent_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'week',
                'date_from': '2019-11-01',
                'date_to': '2019-11-01',
                'type': 'events',
                'entityId': 'sign up',
            },
        ).json()
        self.assertEqual(week_grouped_action_response[0]['people'][0]['id'], person6.pk)
        self.assertEqual(week_grouped_action_response[0]['people'][1]['id'], person7.pk)
        self.assertEqual(len(week_grouped_action_response[0]['people']), 2)
        self.assertTrue(self._compare_entity_response(
            week_grouped_action_response,
            week_grouped_grevent_response,
            remove=[],
        ))

        # check grouped month
        month_group_action_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'month',
                'date_from': '2019-11-01',
                'date_to': '2019-11-01',
                'type': 'actions',
                'entityId': sign_up_action.id,
            },
        ).json()
        month_group_grevent_response = self.client.get(
            '/api/action/people/',
            data={
                'interval': 'month',
                'date_from': '2019-11-01',
                'date_to': '2019-11-01',
                'type': 'events',
                'entityId': 'sign up',
            },
        ).json()
        self.assertEqual(month_group_action_response[0]['people'][0]['id'], person6.pk)
        self.assertEqual(month_group_action_response[0]['people'][1]['id'], person7.pk)
        self.assertEqual(len(month_group_action_response[0]['people']), 2)
        self.assertTrue(self._compare_entity_response(
            month_group_action_response,
            month_group_grevent_response,
            remove=[],
        ))

    def test_stickiness(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=['person1'])
        Event.objects.create(team=self.team, event='watched movie', distinct_id='person1', timestamp='2020-01-01T12:00:00Z')

        Person.objects.create(team=self.team, distinct_ids=['person2'])
        Event.objects.create(team=self.team, event='watched movie', distinct_id='person2', timestamp='2020-01-01T12:00:00Z')
        Event.objects.create(team=self.team, event='watched movie', distinct_id='person2', timestamp='2020-01-02T12:00:00Z')
        # same day
        Event.objects.create(team=self.team, event='watched movie', distinct_id='person2', timestamp='2020-01-02T12:00:00Z')

        Person.objects.create(team=self.team, distinct_ids=['person3'])
        Event.objects.create(team=self.team, event='watched movie', distinct_id='person3', timestamp='2020-01-01T12:00:00Z')
        Event.objects.create(team=self.team, event='watched movie', distinct_id='person3', timestamp='2020-01-02T12:00:00Z')
        Event.objects.create(team=self.team, event='watched movie', distinct_id='person3', timestamp='2020-01-03T12:00:00Z')

        Person.objects.create(team=self.team, distinct_ids=['person4'])
        Event.objects.create(team=self.team, event='watched movie', distinct_id='person4', timestamp='2020-01-05T12:00:00Z')

        watched_movie = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=watched_movie, event='watched movie')
        watched_movie.calculate_events()
        action_response = self.client.get(
            '/api/action/trends/',
            data={
                'shown_as': 'Stickiness',
                'date_from': '2020-01-01',
                'date_to': '2020-01-07',
                'actions': jdumps([{'id': watched_movie.id}]),
            },
        ).json()
        event_response = self.client.get(
            '/api/action/trends/',
            data={
                'shown_as': 'Stickiness',
                'date_from': '2020-01-01',
                'date_to': '2020-01-07',
                'events': jdumps([{'id': "watched movie"}]),
            },
        ).json()
        self.assertEqual(action_response[0]['count'], 4)
        self.assertEqual(action_response[0]['labels'][0], '1 day')
        self.assertEqual(action_response[0]['data'][0], 2)
        self.assertEqual(action_response[0]['labels'][1], '2 days')
        self.assertEqual(action_response[0]['data'][1], 1)
        self.assertEqual(action_response[0]['labels'][2], '3 days')
        self.assertEqual(action_response[0]['data'][2], 1)
        self.assertEqual(action_response[0]['labels'][6], '7 days')
        self.assertEqual(action_response[0]['data'][6], 0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

        # test people
        action_response = self.client.get(
            '/api/action/people/',
            data={
                'shown_as': 'Stickiness',
                'stickiness_days': 1,
                'date_from': '2020-01-01',
                'date_to': '2020-01-07',
                'type': 'actions',
                'entityId': watched_movie.id,
            },
        ).json()
        event_response = self.client.get(
            '/api/action/people/',
            data={
                'shown_as': 'Stickiness',
                'stickiness_days': 1,
                'date_from': '2020-01-01',
                'date_to': '2020-01-07',
                'type': 'events',
                'entityId': 'watched movie',
            },
        ).json()
        self.assertEqual(action_response[0]['people'][0]['id'], person1.pk)

        self.assertTrue(self._compare_entity_response(action_response, event_response, remove=[]))

        # test all time
        response = self.client.get(
            '/api/action/trends/',
            data={
                'shown_as': 'Stickiness',
                'date_from': 'all',
                'date_to': '2020-01-07',
                'actions': jdumps([{'id': watched_movie.id}]),
            },
        ).json()
        self.assertEqual(len(response[0]['data']), 6)
