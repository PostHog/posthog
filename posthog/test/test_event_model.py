from posthog.models import Event, Element, Action, ActionStep, Person
from posthog.api.test.base import BaseTest

class TestEvent(BaseTest):
    def test_filter_with_selectors(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(team=self.team, distinct_id='whatever')
        Element.objects.create(tag_name='div', event=event1, nth_child=0, nth_of_type=0, order=0)
        Element.objects.create(tag_name='a', href='/a-url', event=event1, nth_child=1, nth_of_type=0, order=1)

        event2 = Event.objects.create(team=self.team, distinct_id='whatever')
        Element.objects.create(tag_name='a', event=event2, nth_child=2, nth_of_type=0, order=0, attr_id='someId')
        Element.objects.create(tag_name='div', event=event2, nth_child=0, nth_of_type=0, order=1)
        # make sure elements don't get double counted if they're part of the same event
        Element.objects.create(href='/a-url-2', event=event2, nth_child=0, nth_of_type=0, order=2)

        # test direct decendant ordering
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, tag_name='a', selector='div > a')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event2)

        # test :nth-child()
        action2 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action2, tag_name='a', selector='div > a:nth-child(2)')

        events = Event.objects.filter_by_action(action2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event2)

        # test [id='someId'] 
        action3 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action3, selector="[id='someId']")

        events = Event.objects.filter_by_action(action3)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event2)

    def test_with_normal_filters(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(team=self.team, distinct_id="whatever")
        Element.objects.create(tag_name='a', href='/a-url', text='some_text', event=event1, nth_child=0, nth_of_type=0, order=0)

        event2 = Event.objects.create(team=self.team, distinct_id="whatever")
        Element.objects.create(tag_name='a', href='/a-url-2', text='some_other_text', event=event2, nth_child=0, nth_of_type=0, order=0)
        # make sure elements don't get double counted if they're part of the same event
        Element.objects.create(tag_name='div', text='some_other_text', event=event2, nth_child=0, nth_of_type=0, order=1)

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, href='/a-url', tag_name='a')
        ActionStep.objects.create(action=action1, href='/a-url-2')


        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event2)
        self.assertEqual(events[1], event1)
        self.assertEqual(len(events), 2)

        # test count
        events = Event.objects.filter_by_action(action1, count=True)
        self.assertEqual(events, 2)

    def test_page_views(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(team=self.team, distinct_id='whatever')
        event2 = Event.objects.create(team=self.team, distinct_id='whatever', properties={'$current_url': 'https://posthog.com/feedback/123'})
        Element.objects.create(tag_name='div', text='some_other_text', event=event2, nth_child=0, nth_of_type=0, order=1)

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, url='/feedback')
        ActionStep.objects.create(action=action1, href='/a-url-2')


        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

    def test_person_with_different_distinct_id(self):
        action_watch_movie = Action.objects.create(team=self.team, name='watched movie')
        ActionStep.objects.create(action=action_watch_movie, tag_name='a', href='/movie')

        person = Person.objects.create(distinct_ids=["anonymous_user", "is_now_signed_up"], team=self.team)
        event_watched_movie_anonymous = Event.objects.create(distinct_id='anonymous_user', team=self.team)
        Element.objects.create(tag_name='a', href='/movie', event=event_watched_movie_anonymous)

        event_watched_movie = Event.objects.create(distinct_id='is_now_signed_up', team=self.team)
        Element.objects.create(tag_name='a', href='/movie', event=event_watched_movie)

        events = Event.objects.filter_by_action(action_watch_movie)
        self.assertEqual(events[0], event_watched_movie)
        self.assertEqual(events[0].person_id, person.pk)
