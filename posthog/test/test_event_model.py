from posthog.models import Event, Element, Action, ActionStep
from posthog.api.test.base import BaseTest

class TestEvent(BaseTest):
    def test_filter_with_selectors(self):
        user = self._create_user('timg')
        event1 = Event.objects.create(team=self.team, ip="8.8.8.8")
        Element.objects.create(tag_name='div', event=event1, team=self.team, nth_child=0, nth_of_type=0, order=0)
        Element.objects.create(tag_name='a', href='/a-url', event=event1, team=self.team, nth_child=1, nth_of_type=0, order=1)

        event2 = Event.objects.create(team=self.team, ip="8.8.8.8")
        Element.objects.create(tag_name='a', event=event2, team=self.team, nth_child=2, nth_of_type=0, order=0, attr_id='someId')
        Element.objects.create(tag_name='div', event=event2, team=self.team, nth_child=0, nth_of_type=0, order=1)
        # make sure elements don't get double counted if they're part of the same event
        Element.objects.create(href='/a-url-2', event=event2, team=self.team, nth_child=0, nth_of_type=0, order=2)

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
        user = self._create_user('tim')
        self.client.force_login(user)
        event1 = Event.objects.create(team=self.team, ip="8.8.8.8")
        Element.objects.create(tag_name='a', href='/a-url', text='some_text', event=event1, team=self.team, nth_child=0, nth_of_type=0, order=0)

        event2 = Event.objects.create(team=self.team, ip="8.8.8.8")
        Element.objects.create(tag_name='a', href='/a-url-2', text='some_other_text', event=event2, team=self.team, nth_child=0, nth_of_type=0, order=0)
        # make sure elements don't get double counted if they're part of the same event
        Element.objects.create(tag_name='div', text='some_other_text', event=event2, team=self.team, nth_child=0, nth_of_type=0, order=1)

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, href='/a-url', tag_name='a')
        ActionStep.objects.create(action=action1, href='/a-url-2')


        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event1)
        self.assertEqual(len(events), 2)

        # test count
        events = Event.objects.filter_by_action(action1, count=True)
        self.assertEqual(events, 2)