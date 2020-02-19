from posthog.models import Event, Element, Action, ActionStep, Person, Team
from posthog.api.test.base import BaseTest

class TestFilterByActions(BaseTest):
    def test_filter_with_selectors(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(event='$autocapture', team=self.team, distinct_id='whatever')
        Element.objects.create(tag_name='div', event=event1, nth_child=0, nth_of_type=0, order=0)
        Element.objects.create(tag_name='a', href='/a-url', event=event1, nth_child=1, nth_of_type=0, order=1)

        event2 = Event.objects.create(event='$autocapture', team=self.team, distinct_id='whatever')
        Element.objects.create(tag_name='a', event=event2, nth_child=2, nth_of_type=0, order=0, attr_id='someId')
        Element.objects.create(tag_name='div', event=event2, nth_child=0, nth_of_type=0, order=1)
        # make sure elements don't get double counted if they're part of the same event
        Element.objects.create(href='/a-url-2', event=event2, nth_child=0, nth_of_type=0, order=2)

        # make sure other teams' data doesn't get mixed in
        team2 = Team.objects.create()
        event3 = Event.objects.create(event='$autocapture', team=team2, distinct_id='whatever')
        Element.objects.create(tag_name='a', event=event3, nth_child=2, nth_of_type=0, order=0, attr_id='someId')
        Element.objects.create(tag_name='div', event=event3, nth_child=0, nth_of_type=0, order=1)

        # test direct decendant ordering
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(event='$autocapture', action=action1, tag_name='a', selector='div > a')

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

        event3 = Event.objects.create(team=self.team, distinct_id="whatever")

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, href='/a-url', tag_name='a')
        ActionStep.objects.create(action=action1, href='/a-url-2')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event2)
        self.assertEqual(events[1], event1)
        self.assertEqual(len(events), 2)

        # test count
        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events.count(), 2)

    def test_with_class(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(team=self.team, distinct_id="whatever")
        Element.objects.create(event=event1, tag_name='span', attr_class=None, order=0)
        Element.objects.create(event=event1, tag_name='a', attr_class=['active', 'nav-link'], order=1)

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, selector='a.nav-link.active', tag_name='a')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event1)
        self.assertEqual(len(events), 1)

    def test_with_text(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(team=self.team, distinct_id="whatever")
        Element.objects.create(event=event1, tag_name='span', text='whatever', order=0)

        event2 = Event.objects.create(team=self.team, distinct_id="whatever")
        Element.objects.create(event=event2, tag_name='span', text='whatever2', order=0)

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, text='whatever')

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event1)
        self.assertEqual(len(events), 1)

    def test_page_views(self):
        Person.objects.create(distinct_ids=['whatever'], team=self.team)
        event1 = Event.objects.create(team=self.team, distinct_id='whatever')
        event2 = Event.objects.create(event='bla', team=self.team, distinct_id='whatever', properties={'$current_url': 'bla'})
        Element.objects.create(tag_name='div', text='some_other_text', event=event2, nth_child=0, nth_of_type=0, order=1)

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, event='bla')
        # ActionStep.objects.create(action=action1, href='/a-url-2')


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


class TestActions(BaseTest):
    def _signup_event(self, distinct_id: str):
        sign_up = Event.objects.create(distinct_id=distinct_id, team=self.team)
        Element.objects.create(tag_name='button', text='Sign up!', event=sign_up)
        return sign_up

    def _movie_event(self, distinct_id: str):
        event = Event.objects.create(distinct_id=distinct_id, team=self.team)
        Element.objects.create(tag_name='a', attr_class=['watch_movie', 'play'], text='Watch now', attr_id='something', href='/movie', event=event, order=0)
        Element.objects.create(tag_name='div', href='/movie', event=event, order=1)
        return event

    def test_simple_element_filters(self):
        action_sign_up = Action.objects.create(team=self.team, name='signed up')
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')
        # 2 steps that match same element might trip stuff up
        ActionStep.objects.create(action=action_sign_up, tag_name='button', text='Sign up!')
        action_credit_card = Action.objects.create(team=self.team, name='paid')
        ActionStep.objects.create(action=action_credit_card, tag_name='button', text='Pay $10')

        # events
        person_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup"], team=self.team)
        event_sign_up_1 = self._signup_event('stopped_after_signup')
        self.assertEqual(event_sign_up_1.actions, [action_sign_up])

    def test_selector(self):
        action_watch_movie = Action.objects.create(team=self.team, name='watch movie')
        ActionStep.objects.create(action=action_watch_movie, text='Watch now', selector="div > a.watch_movie")
        Person.objects.create(distinct_ids=["watched_movie"], team=self.team)
        event = self._movie_event('watched_movie')
        self.assertEqual(event.actions, [action_watch_movie])

    def test_event_filter(self):
        action_user_paid = Action.objects.create(team=self.team, name='user paid')
        ActionStep.objects.create(action=action_user_paid, event='user paid')
        Person.objects.create(distinct_ids=["user_paid"], team=self.team)
        event = Event.objects.create(event='user paid', distinct_id='user_paid', team=self.team)
        self.assertEqual(event.actions, [action_user_paid])

    def test_element_class_set_to_none(self):
        action_user_paid = Action.objects.create(team=self.team, name='user paid')
        ActionStep.objects.create(action=action_user_paid, selector='a.something')
        Person.objects.create(distinct_ids=["user_paid"], team=self.team)
        event = Event.objects.create(event='$autocapture', distinct_id='user_paid', team=self.team)
        Element.objects.create(event=event, tag_name='a', attr_class=None, order=0)
        # This would error when attr_class wasn't set.
        self.assertEqual(event.actions, [])