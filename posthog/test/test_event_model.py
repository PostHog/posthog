from posthog.models import Event, Element, Action, ActionStep, Person, Team, ElementGroup
from posthog.api.test.base import BaseTest

class TestFilterByActions(BaseTest):
    def test_filter_with_selectors(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)

        event1 = Event.objects.create(event='$autocapture', team=self.team, distinct_id='whatever', elements=[
            Element(tag_name='div', nth_child=0, nth_of_type=0, order=0),
            Element(tag_name='a', href='/a-url', nth_child=1, nth_of_type=0, order=1)
        ])

        event2 = Event.objects.create(event='$autocapture', team=self.team, distinct_id='whatever', elements=[
            Element(tag_name='a', nth_child=2, nth_of_type=0, order=0, attr_id='someId'),
            Element(tag_name='div', nth_child=0, nth_of_type=0, order=1),
            # make sure elements don't get double counted if they're part of the same event
            Element(href='/a-url-2', nth_child=0, nth_of_type=0, order=2)
        ])

        # make sure other teams' data doesn't get mixed in
        team2 = Team.objects.create()
        event3 = Event.objects.create(event='$autocapture', team=team2, distinct_id='whatever', elements=[
            Element(tag_name='a', nth_child=2, nth_of_type=0, order=0, attr_id='someId'),
            Element(tag_name='div', nth_child=0, nth_of_type=0, order=1)
        ])

        # test direct decendant ordering
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(event='$autocapture', action=action1, selector='div > a')
        ActionStep.objects.create(event='$autocapture', action=action1, selector='div > a.somethingthatdoesntexist')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event2)

        # test :nth-child()
        action2 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action2, selector='div > a:nth-child(2)')

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
        event1 = Event.objects.create(team=self.team, distinct_id="whatever", elements=[
            Element(tag_name='a', href='/a-url', text='some_text', nth_child=0, nth_of_type=0, order=0)
        ])

        event2 = Event.objects.create(team=self.team, distinct_id="whatever", elements=[
            Element(tag_name='a', href='/a-url-2', text='some_other_text', nth_child=0, nth_of_type=0, order=0),
            # make sure elements don't get double counted if they're part of the same event
            Element(tag_name='div', text='some_other_text', nth_child=0, nth_of_type=0, order=1)
        ])

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, href='/a-url', tag_name='a')
        ActionStep.objects.create(action=action1, href='/a-url-2')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event2)
        self.assertEqual(events[1], event1)
        self.assertEqual(len(events), 2)

    def test_with_class(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(team=self.team, distinct_id="whatever", elements=[
            Element(tag_name='span', attr_class=None, order=0),
            Element(tag_name='a', attr_class=['active', 'nav-link'], order=1)
        ])

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, selector='a.nav-link.active', tag_name='a')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event1)
        self.assertEqual(len(events), 1)

    def test_attributes(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)

        event1 = Event.objects.create(team=self.team, distinct_id="whatever", elements=[
            Element(tag_name='span', order=0),
            Element(tag_name='a', order=1, attributes={'data-id': '123'})
        ])

        event2 = Event.objects.create(team=self.team, distinct_id="whatever", elements=[
            Element(tag_name='button', order=0, attributes={'data-id': '123'})
        ])

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, selector='a[data-id="123"]')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event1)

    def test_filter_events_by_url(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(team=self.team, distinct_id='whatever')

        event2 = Event.objects.create(team=self.team, distinct_id='whatever', properties={'$current_url': 'https://posthog.com/feedback/123'}, elements=[
            Element(tag_name='div', text='some_other_text', nth_child=0, nth_of_type=0, order=1)
        ])

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, url='https://posthog.com/feedback/123')
        ActionStep.objects.create(action=action1, href='/a-url-2')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

    def test_person_with_different_distinct_id(self):
        action_watch_movie = Action.objects.create(team=self.team, name='watched movie')
        ActionStep.objects.create(action=action_watch_movie, tag_name='a', href='/movie')

        person = Person.objects.create(distinct_ids=["anonymous_user", "is_now_signed_up"], team=self.team)
        event_watched_movie_anonymous = Event.objects.create(distinct_id='anonymous_user', team=self.team, elements=[
            Element(tag_name='a', href='/movie')
        ])

        event_watched_movie = Event.objects.create(distinct_id='is_now_signed_up', team=self.team, elements=[
            Element(tag_name='a', href='/movie')
        ])

        events = Event.objects.filter_by_action(action_watch_movie)
        self.assertEqual(events[0], event_watched_movie)
        self.assertEqual(events[0].person_id, person.pk)

    def test_no_person_leakage_from_other_teams(self):
        action_watch_movie = Action.objects.create(team=self.team, name='watched movie')
        ActionStep.objects.create(action=action_watch_movie, event='user signed up')

        person = Person.objects.create(distinct_ids=["anonymous_user"], team=self.team)
        event_watched_movie_anonymous = Event.objects.create(event='user signed up', distinct_id='anonymous_user', team=self.team)

        team2 = Team.objects.create()
        person2 = Person.objects.create(distinct_ids=["anonymous_user"], team=team2)

        events = Event.objects.filter_by_action(action_watch_movie)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].person_id, person.pk)


class TestElementGroup(BaseTest):
    def test_create_elements(self):
        elements = [
            Element(tag_name='button', text='Sign up!'),
            Element(tag_name='div')
        ]
        group1 = ElementGroup.objects.create(team=self.team, elements=elements)
        elements = Element.objects.all()
        self.assertEqual(elements[0].tag_name, 'button')
        self.assertEqual(elements[1].tag_name, 'div')

        elements = [
            Element(tag_name='button', text='Sign up!'),
            # make sure we remove events if we can
            Element(tag_name='div', event=Event.objects.create(team=self.team))
        ]
        group2 = ElementGroup.objects.create(team=self.team, elements=elements)
        self.assertEqual(Element.objects.count(), 2)
        self.assertEqual(group1.hash, group2.hash)