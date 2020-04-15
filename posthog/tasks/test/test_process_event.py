from posthog.api.test.base import BaseTest
from unittest.mock import patch, call
from posthog.tasks.process_event import process_event
from posthog.models import Event, Action, ActionStep, Person, ElementGroup, Team
from django.utils.timezone import now


class ProcessEvent(BaseTest):
    def test_capture_new_person(self):
        user = self._create_user('tim')
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, selector='a')
        action2 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action2, selector='a')

        with self.assertNumQueries(18):
            process_event('', '', {
                'event': '$autocapture',
                'properties': {
                    'distinct_id': 2,
                    'token': self.team.api_token,
                    '$elements': [
                        {'tag_name': 'a', 'nth_child': 1, 'nth_of_type': 2, 'attr__class': 'btn btn-sm'},
                        {'tag_name': 'div', 'nth_child': 1, 'nth_of_type': 2, '$el_text': '💻'}
                    ]
                },
            }, self.team.pk, now())

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

        process_event('', '', {
            'event': '$pageview',
            'properties': {
                'distinct_id': 'asdfasdfasdf',
                'token': self.team.api_token,
            },
        }, self.team.pk, now())

        self.assertEqual(Person.objects.get().distinct_ids, ["asdfasdfasdf"])
        event = Event.objects.get()
        self.assertEqual(event.event, '$pageview')

    # def test_emojis_in_text(self):
    #     self.team.api_token = 'xp9qT2VLY76JJg'
    #     self.team.save()
    #     response = self.client.post('/track/', data={
    #         'data': "eyJldmVudCI6ICIkd2ViX2V2ZW50IiwicHJvcGVydGllcyI6IHsiJG9zIjogIk1hYyBPUyBYIiwiJGJyb3dzZXIiOiAiQ2hyb21lIiwiJHJlZmVycmVyIjogImh0dHBzOi8vYXBwLmhpYmVybHkuY29tL2xvZ2luP25leHQ9LyIsIiRyZWZlcnJpbmdfZG9tYWluIjogImFwcC5oaWJlcmx5LmNvbSIsIiRjdXJyZW50X3VybCI6ICJodHRwczovL2FwcC5oaWJlcmx5LmNvbS8iLCIkYnJvd3Nlcl92ZXJzaW9uIjogNzksIiRzY3JlZW5faGVpZ2h0IjogMjE2MCwiJHNjcmVlbl93aWR0aCI6IDM4NDAsInBoX2xpYiI6ICJ3ZWIiLCIkbGliX3ZlcnNpb24iOiAiMi4zMy4xIiwiJGluc2VydF9pZCI6ICJnNGFoZXFtejVrY3AwZ2QyIiwidGltZSI6IDE1ODA0MTAzNjguMjY1LCJkaXN0aW5jdF9pZCI6IDYzLCIkZGV2aWNlX2lkIjogIjE2ZmQ1MmRkMDQ1NTMyLTA1YmNhOTRkOWI3OWFiLTM5NjM3YzBlLTFhZWFhMC0xNmZkNTJkZDA0NjQxZCIsIiRpbml0aWFsX3JlZmVycmVyIjogIiRkaXJlY3QiLCIkaW5pdGlhbF9yZWZlcnJpbmdfZG9tYWluIjogIiRkaXJlY3QiLCIkdXNlcl9pZCI6IDYzLCIkZXZlbnRfdHlwZSI6ICJjbGljayIsIiRjZV92ZXJzaW9uIjogMSwiJGhvc3QiOiAiYXBwLmhpYmVybHkuY29tIiwiJHBhdGhuYW1lIjogIi8iLCIkZWxlbWVudHMiOiBbCiAgICB7InRhZ19uYW1lIjogImJ1dHRvbiIsIiRlbF90ZXh0IjogIu2gve2yuyBXcml0aW5nIGNvZGUiLCJjbGFzc2VzIjogWwogICAgImJ0biIsCiAgICAiYnRuLXNlY29uZGFyeSIKXSwiYXR0cl9fY2xhc3MiOiAiYnRuIGJ0bi1zZWNvbmRhcnkiLCJhdHRyX19zdHlsZSI6ICJjdXJzb3I6IHBvaW50ZXI7IG1hcmdpbi1yaWdodDogOHB4OyBtYXJnaW4tYm90dG9tOiAxcmVtOyIsIm50aF9jaGlsZCI6IDIsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiZmVlZGJhY2stc3RlcCIsCiAgICAiZmVlZGJhY2stc3RlcC1zZWxlY3RlZCIKXSwiYXR0cl9fY2xhc3MiOiAiZmVlZGJhY2stc3RlcCBmZWVkYmFjay1zdGVwLXNlbGVjdGVkIiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJnaXZlLWZlZWRiYWNrIgpdLCJhdHRyX19jbGFzcyI6ICJnaXZlLWZlZWRiYWNrIiwiYXR0cl9fc3R5bGUiOiAid2lkdGg6IDkwJTsgbWFyZ2luOiAwcHggYXV0bzsgZm9udC1zaXplOiAxNXB4OyBwb3NpdGlvbjogcmVsYXRpdmU7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9fc3R5bGUiOiAib3ZlcmZsb3c6IGhpZGRlbjsiLCJudGhfY2hpbGQiOiAxLCJudGhfb2ZfdHlwZSI6IDF9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgIm1vZGFsLWJvZHkiCl0sImF0dHJfX2NsYXNzIjogIm1vZGFsLWJvZHkiLCJhdHRyX19zdHlsZSI6ICJmb250LXNpemU6IDE1cHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1jb250ZW50IgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1jb250ZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbC1kaWFsb2ciLAogICAgIm1vZGFsLWxnIgpdLCJhdHRyX19jbGFzcyI6ICJtb2RhbC1kaWFsb2cgbW9kYWwtbGciLCJhdHRyX19yb2xlIjogImRvY3VtZW50IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJtb2RhbCIsCiAgICAiZmFkZSIsCiAgICAic2hvdyIKXSwiYXR0cl9fY2xhc3MiOiAibW9kYWwgZmFkZSBzaG93IiwiYXR0cl9fc3R5bGUiOiAiZGlzcGxheTogYmxvY2s7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJrLXBvcnRsZXRfX2JvZHkiLAogICAgIiIKXSwiYXR0cl9fY2xhc3MiOiAiay1wb3J0bGV0X19ib2R5ICIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDBweDsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJjbGFzc2VzIjogWwogICAgImstcG9ydGxldCIsCiAgICAiay1wb3J0bGV0LS1oZWlnaHQtZmx1aWQiCl0sImF0dHJfX2NsYXNzIjogImstcG9ydGxldCBrLXBvcnRsZXQtLWhlaWdodC1mbHVpZCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImNsYXNzZXMiOiBbCiAgICAiY29sLWxnLTYiCl0sImF0dHJfX2NsYXNzIjogImNvbC1sZy02IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJyb3ciCl0sImF0dHJfX2NsYXNzIjogInJvdyIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImRpdiIsImF0dHJfX3N0eWxlIjogInBhZGRpbmc6IDQwcHggMzBweCAwcHg7IGJhY2tncm91bmQtY29sb3I6IHJnYigyMzksIDIzOSwgMjQ1KTsgbWFyZ2luLXRvcDogLTQwcHg7IG1pbi1oZWlnaHQ6IGNhbGMoMTAwdmggLSA0MHB4KTsiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDJ9LAogICAgeyJ0YWdfbmFtZSI6ICJkaXYiLCJhdHRyX19zdHlsZSI6ICJtYXJnaW4tdG9wOiAwcHg7IiwibnRoX2NoaWxkIjogMiwibnRoX29mX3R5cGUiOiAyfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiY2xhc3NlcyI6IFsKICAgICJBcHAiCl0sImF0dHJfX2NsYXNzIjogIkFwcCIsImF0dHJfX3N0eWxlIjogImNvbG9yOiByZ2IoNTIsIDYxLCA2Mik7IiwibnRoX2NoaWxkIjogMSwibnRoX29mX3R5cGUiOiAxfSwKICAgIHsidGFnX25hbWUiOiAiZGl2IiwiYXR0cl9faWQiOiAicm9vdCIsIm50aF9jaGlsZCI6IDEsIm50aF9vZl90eXBlIjogMX0sCiAgICB7InRhZ19uYW1lIjogImJvZHkiLCJudGhfY2hpbGQiOiAyLCJudGhfb2ZfdHlwZSI6IDF9Cl0sInRva2VuIjogInhwOXFUMlZMWTc2SkpnIn19"
    #     })

    #     self.assertEqual(Person.objects.get().distinct_ids, ["63"])
    #     event = Event.objects.get()
    #     element = ElementGroup.objects.get(hash=event.elements_hash).element_set.all().first()
    #     assert element is not None
    #     self.assertEqual(element.text, '💻 Writing code')

    def test_alias(self):
        Person.objects.create(team=self.team, distinct_ids=['old_distinct_id'])

        process_event('', '', {
            'event': '$create_alias',
            'properties': {
                'distinct_id': 'old_distinct_id',
                'token': self.team.api_token,
                'alias': 'new_distinct_id'
            },
        }, self.team.pk, now())

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Person.objects.get().distinct_ids, ["old_distinct_id", "new_distinct_id"])

    # This tends to happen when .init and .identify get called right after each other, causing a race condition
    # in this case the 'anonymous_id' won't have any actions anyway
    def test_alias_to_non_existent_distinct_id(self):
        process_event('', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'doesnt_exist',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now())

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Person.objects.get().distinct_ids, ['new_distinct_id'])


class TestIdentify(BaseTest):
    def test_distinct_with_anonymous_id(self):
        Person.objects.create(team=self.team, distinct_ids=['anonymous_id'])

        process_event('', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'anonymous_id',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now())

        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(Person.objects.get().distinct_ids, ["anonymous_id", "new_distinct_id"])

        # check no errors as this call can happen multiple times
        process_event('', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'anonymous_id',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now())

    # This case is likely to happen after signup, for example:
    # 1. User browses website with anonymous_id
    # 2. User signs up, triggers event with their new_distinct_id (creating a new Person)
    # 3. In the frontend, try to alias anonymous_id with new_distinct_id
    # Result should be that we end up with one Person with both ID's
    def test_distinct_with_anonymous_id_which_was_already_created(self):
        Person.objects.create(team=self.team, distinct_ids=['anonymous_id'])
        Person.objects.create(team=self.team, distinct_ids=['new_distinct_id'], properties={'email': 'someone@gmail.com'})

        process_event('', '', {
            'event': '$identify',
            'properties': {
                '$anon_distinct_id': 'anonymous_id',
                'token': self.team.api_token,
                'distinct_id': 'new_distinct_id'
            },
        }, self.team.pk, now())

        # self.assertEqual(Event.objects.count(), 0)
        person = Person.objects.get()
        self.assertEqual(person.distinct_ids, ["anonymous_id", "new_distinct_id"])
        self.assertEqual(person.properties['email'], 'someone@gmail.com')

    def test_distinct_team_leakage(self):
        team2 = Team.objects.create()
        Person.objects.create(team=team2, distinct_ids=['2'], properties={'email': 'team2@gmail.com'})
        Person.objects.create(team=self.team, distinct_ids=['1', '2'])

        try:
            process_event('', '', {
                'event': '$identify',
                'properties': {
                    '$anon_distinct_id': '1',
                    'token': self.team.api_token,
                    'distinct_id': '2'
                },
            }, self.team.pk, now())
        except:
            pass

        people = Person.objects.all()
        self.assertEqual(people.count(), 2)
        self.assertEqual(people[1].team, self.team)
        self.assertEqual(people[1].properties, {})
        self.assertEqual(people[1].distinct_ids, ["1", "2"])
        self.assertEqual(people[0].team, team2)
        self.assertEqual(people[0].distinct_ids, ["2"])