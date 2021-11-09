from freezegun import freeze_time

from posthog.models import Action, ActionStep, Element, ElementGroup, Event, Organization, Person
from posthog.models.event import Selector
from posthog.tasks.calculate_action import calculate_actions_from_last_calculation
from posthog.test.base import BaseTest


def _create_action(team, steps):
    action = Action.objects.create(team=team)
    for step in steps:
        ActionStep.objects.create(action=action, **step)

    action.calculate_events()

    return action


def filter_by_actions_factory(_create_event, _create_person, _get_events_for_action):
    class TestFilterByActions(BaseTest):
        def test_filter_with_selector_direct_decendant_ordering(self):
            all_events = self._setup_action_selector_events()
            action = _create_action(
                self.team,
                [
                    {"event": "$autocapture", "selector": "div > div > a"},
                    {"event": "$autocapture", "selector": "div > a.somethingthatdoesntexist"},
                ],
            )

            self.assertActionEventsMatch(action, [all_events[1]])

        def test_filter_with_selector_nth_child(self):
            all_events = self._setup_action_selector_events()
            action = _create_action(self.team, [{"event": "$autocapture", "selector": "div > a:nth-child(2)"}])

            self.assertActionEventsMatch(action, [all_events[1]])

        def test_filter_with_selector_id(self):
            all_events = self._setup_action_selector_events()
            action = _create_action(self.team, [{"event": "$autocapture", "selector": "[id='someId']"}])

            self.assertActionEventsMatch(action, [all_events[1]])

        def test_filter_with_selector_nested(self):
            all_events = self._setup_action_selector_events()
            action = _create_action(self.team, [{"event": "$autocapture", "selector": "[id='nested'] a"}])

            self.assertActionEventsMatch(action, [all_events[0]])

        def test_filter_with_selector_star(self):
            all_events = self._setup_action_selector_events()
            action = _create_action(self.team, [{"event": "$autocapture", "selector": "div *"}])

            self.assertActionEventsMatch(action, all_events)

        def _setup_action_selector_events(self):
            _create_person(distinct_ids=["whatever"], team=self.team)

            event1 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="a", href="/a-url", nth_child=1, nth_of_type=0, attr_class=["one-class"]),
                    Element(tag_name="button", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested",),
                ],
            )

            event2 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="a", nth_child=2, nth_of_type=0, attr_id="someId"),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(href="/a-url-2", nth_child=0, nth_of_type=0),
                ],
            )

            event3 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="a", nth_child=3, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                ],
            )

            # make sure other teams' data doesn't get mixed in
            team2 = Organization.objects.bootstrap(None)[2]
            _create_event(
                event="$autocapture",
                team=team2,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="a", nth_child=2, nth_of_type=0, attr_id="someId"),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                ],
            )

            return event1, event2, event3

        def assertActionEventsMatch(self, action, expected_events):
            events = _get_events_for_action(action)

            self.assertCountEqual([e.pk for e in events], [e.pk for e in expected_events])

        def test_with_normal_filters(self):
            # this test also specifically tests the back to back receipt of
            # the same type of events by action to test the query cache
            _create_person(distinct_ids=["whatever"], team=self.team)
            # _create_person(distinct_ids=["whatever2"], team=self.team)

            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(event="$autocapture", action=action1, href="/a-url", selector="a")
            ActionStep.objects.create(event="$autocapture", action=action1, href="/a-url-2")

            team2 = Organization.objects.bootstrap(None)[2]
            event1 = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever",
                elements=[Element(tag_name="a", href="/a-url", text="some_text", nth_child=0, nth_of_type=0,)],
            )

            event2 = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[Element(tag_name="a", href="/a-url", text="some_text", nth_child=0, nth_of_type=0,)],
            )

            event3 = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever",
                elements=[
                    Element(tag_name="a", href="/a-url-2", text="some_other_text", nth_child=0, nth_of_type=0,),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(tag_name="div", text="some_other_text", nth_child=0, nth_of_type=0,),
                ],
            )

            event4 = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[
                    Element(tag_name="a", href="/a-url-2", text="some_other_text", nth_child=0, nth_of_type=0,),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(tag_name="div", text="some_other_text", nth_child=0, nth_of_type=0,),
                ],
            )

            # team leakage
            _create_event(
                team=team2,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[Element(tag_name="a", href="/a-url", text="some_other_text", nth_child=0, nth_of_type=0,),],
            )
            _create_event(
                team=team2,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[Element(tag_name="a", href="/a-url-2", text="some_other_text", nth_child=0, nth_of_type=0,),],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 4)
            self.assertEqual(events[0].pk, event4.pk)
            self.assertEqual(events[1].pk, event3.pk)
            self.assertEqual(events[2].pk, event2.pk)
            self.assertEqual(events[3].pk, event1.pk)

        def test_with_class(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(event="$autocapture", action=action1, selector="a.nav-link.active", tag_name="a")
            event1 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="span", attr_class=None),
                    # crazy-class makes sure we don't require exact matching of the entire class string
                    Element(tag_name="a", attr_class=["active", "crazy-class", "nav-link"]),
                ],
            )
            # no class
            _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[Element(tag_name="span", attr_class=None), Element(tag_name="a", attr_class=None),],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(events[0].pk, event1.pk)
            self.assertEqual(len(events), 1)

        def test_with_class_with_escaped_symbols(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture", action=action1, selector="a.na\\\\v-link\\:b\\@ld", tag_name="a"
            )
            event1 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="span", attr_class=None),
                    Element(tag_name="a", attr_class=["na\\v-link:b@ld"]),
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(events[0].pk, event1.pk)
            self.assertEqual(len(events), 1)

        def test_with_class_with_escaped_slashes(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture", action=action1, selector="a.na\\\\\\\\\\\\v-link\\:b\\@ld", tag_name="a"
            )
            event1 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="span", attr_class=None),
                    Element(tag_name="a", attr_class=["na\\\\\\v-link:b@ld"]),
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(events[0].pk, event1.pk)
            self.assertEqual(len(events), 1)

        def test_attributes(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            event1 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[Element(tag_name="button", attributes={"attr__data-id": "123"})],
            )

            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(event="$autocapture", action=action1, selector='[data-id="123"]')
            action1.calculate_events()

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].pk, event1.pk)

        def test_filter_events_by_url(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture",
                action=action1,
                url="https://posthog.com/feedback/123",
                url_matching=ActionStep.EXACT,
            )
            ActionStep.objects.create(event="$autocapture", action=action1, href="/a-url-2")

            action2 = Action.objects.create(team=self.team)
            ActionStep.objects.create(event="$autocapture", action=action2, url="123", url_matching=ActionStep.CONTAINS)

            action3 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture", action=action3, url="https://posthog.com/%/123", url_matching=ActionStep.CONTAINS,
            )

            action4 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture", action=action4, url="/123$", url_matching=ActionStep.REGEX,
            )

            event1 = _create_event(team=self.team, distinct_id="whatever", event="$autocapture")
            event2 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                properties={"$current_url": "https://posthog.com/feedback/123"},
                elements=[Element(tag_name="div", text="some_other_text", nth_child=0, nth_of_type=0,)],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(events[0].pk, event2.pk)
            self.assertEqual(len(events), 1)

            events = _get_events_for_action(action2)
            self.assertEqual(events[0].pk, event2.pk)
            self.assertEqual(len(events), 1)

            events = _get_events_for_action(action3)
            self.assertEqual(events[0].pk, event2.pk)
            self.assertEqual(len(events), 1)

            events = _get_events_for_action(action4)
            self.assertEqual(events[0].pk, event2.pk)
            self.assertEqual(len(events), 1)

        def test_person_with_different_distinct_id(self):
            action_watch_movie = Action.objects.create(team=self.team, name="watched movie")
            ActionStep.objects.create(action=action_watch_movie, tag_name="a", href="/movie", event="$autocapture")

            person = _create_person(distinct_ids=["anonymous_user", "is_now_signed_up"], team=self.team)
            event_watched_movie_anonymous = _create_event(
                distinct_id="anonymous_user",
                team=self.team,
                elements=[Element(tag_name="a", href="/movie")],
                event="$autocapture",
            )

            event_watched_movie = _create_event(
                distinct_id="is_now_signed_up",
                team=self.team,
                elements=[Element(tag_name="a", href="/movie")],
                event="$autocapture",
            )

            events = _get_events_for_action(action_watch_movie)
            self.assertEqual(events[0].pk, event_watched_movie.pk)
            self.assertEqual(events[0].distinct_id, "is_now_signed_up")

        def test_no_person_leakage_from_other_teams(self):
            action_watch_movie = Action.objects.create(team=self.team, name="watched movie")
            ActionStep.objects.create(action=action_watch_movie, event="user signed up")

            person = _create_person(distinct_ids=["anonymous_user"], team=self.team)
            event_watched_movie_anonymous = _create_event(
                event="user signed up", distinct_id="anonymous_user", team=self.team
            )

            team2 = Organization.objects.bootstrap(None)[2]
            person2 = _create_person(distinct_ids=["anonymous_user2"], team=team2)

            events = _get_events_for_action(action_watch_movie)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].distinct_id, "anonymous_user")

        def test_person_property(self):
            _create_person(team=self.team, distinct_ids=["person1"], properties={"$browser": "Chrome"})
            _create_person(team=self.team, distinct_ids=["person2"])
            _create_event(event="$pageview", distinct_id="person1", team=self.team)
            _create_event(event="$pageview", distinct_id="person2", team=self.team)
            action = Action.objects.create(name="pageview", team=self.team)
            ActionStep.objects.create(
                action=action, event="$pageview", properties=[{"key": "$browser", "value": "Chrome", "type": "person"}],
            )
            action.calculate_events()
            events = _get_events_for_action(action)
            self.assertEqual(len(events), 1)

        def test_no_steps(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            event1 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[Element(tag_name="button", attributes={"attr__data-id": "123"})],
            )
            action1 = Action.objects.create(team=self.team)
            action1.calculate_events()

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 0)

        def test_empty_selector_same_as_null(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action_null_selector = Action.objects.create(team=self.team)
            ActionStep.objects.create(action=action_null_selector, event="$autocapture", selector=None)
            action_empty_selector = Action.objects.create(team=self.team)
            ActionStep.objects.create(action=action_empty_selector, event="$autocapture", selector="")
            event1 = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[Element(tag_name="span", attr_class=None)],
            )

            events_null_selector = _get_events_for_action(action_null_selector)
            self.assertEqual(events_null_selector[0].pk, event1.pk)
            self.assertEqual(len(events_null_selector), 1)

            events_empty_selector = _get_events_for_action(action_empty_selector)
            self.assertEqual(events_empty_selector, events_null_selector)

    return TestFilterByActions


filter_by_actions_factory(Event.objects.create, Person.objects.create, Event.objects.filter_by_action)


class TestElementGroup(BaseTest):
    def test_create_elements(self):
        elements = [
            Element(tag_name="button", text="Sign up!",),
            Element(tag_name="div",),
        ]
        group1 = ElementGroup.objects.create(team=self.team, elements=elements)
        elements = list(Element.objects.all())
        self.assertEqual(elements[0].tag_name, "button")
        self.assertEqual(elements[1].tag_name, "div")

        elements = [
            Element(tag_name="button", text="Sign up!",),
            # make sure we remove events if we can
            Element(tag_name="div", event=Event.objects.create(team=self.team),),
        ]
        group2 = ElementGroup.objects.create(team=self.team, elements=elements)
        self.assertEqual(Element.objects.count(), 2)
        self.assertEqual(group1.hash, group2.hash)

        # Test no team leakage
        team2 = Organization.objects.bootstrap(None)[2]
        group3 = ElementGroup.objects.create(team=team2, elements=elements)
        group3_duplicate = ElementGroup.objects.create(team_id=team2.pk, elements=elements)
        self.assertNotEqual(group2, group3)
        self.assertEqual(group3, group3_duplicate)
        self.assertEqual(ElementGroup.objects.count(), 2)


class TestActions(BaseTest):
    def _signup_event(self, distinct_id: str):
        sign_up = Event.objects.create(
            distinct_id=distinct_id,
            team=self.team,
            event="$autocapture",
            elements=[Element(tag_name="button", text="Sign up!")],
        )
        return sign_up

    def _movie_event(self, distinct_id: str):
        event = Event.objects.create(
            distinct_id=distinct_id,
            team=self.team,
            event="$autocapture",
            elements=[
                Element(
                    tag_name="a",
                    attr_class=["watch_movie", "play"],
                    text="Watch now",
                    attr_id="something",
                    href="/movie",
                ),
                Element(tag_name="div", href="/movie"),
            ],
        )
        return event

    def test_simple_element_filters(self):
        action_sign_up = Action.objects.create(team=self.team, name="signed up")
        ActionStep.objects.create(
            action=action_sign_up, tag_name="button", text="Sign up!", event="$autocapture",
        )
        # 2 steps that match same element might trip stuff up
        ActionStep.objects.create(
            action=action_sign_up, tag_name="button", text="Sign up!", event="$autocapture",
        )
        action_credit_card = Action.objects.create(team=self.team, name="paid")
        ActionStep.objects.create(
            action=action_credit_card, tag_name="button", text="Pay $10", event="$autocapture",
        )

        # events
        person_stopped_after_signup = Person.objects.create(distinct_ids=["stopped_after_signup"], team=self.team)
        event_sign_up_1 = self._signup_event("stopped_after_signup")
        self.assertEqual(event_sign_up_1.actions, [action_sign_up])

    def test_selector(self):
        action_watch_movie = Action.objects.create(team=self.team, name="watch movie")
        ActionStep.objects.create(
            action=action_watch_movie, text="Watch now", selector="div > a.watch_movie", event="$autocapture",
        )
        Person.objects.create(distinct_ids=["watched_movie"], team=self.team)
        event = self._movie_event("watched_movie")
        self.assertEqual(event.actions, [action_watch_movie])

    def test_attributes(self):
        action = Action.objects.create(team=self.team, name="watch movie")
        ActionStep.objects.create(action=action, selector="a[data-id='whatever']")
        action2 = Action.objects.create(team=self.team, name="watch movie2")
        ActionStep.objects.create(action=action2, selector="a[somethingelse='whatever']")
        Person.objects.create(distinct_ids=["watched_movie"], team=self.team)
        event = Event.objects.create(
            team=self.team,
            distinct_id="whatever",
            elements=[Element(tag_name="a", attributes={"attr__data-id": "whatever"})],
        )
        self.assertEqual(event.actions, [action])

    def test_event_filter(self):
        action_user_paid = Action.objects.create(team=self.team, name="user paid")
        ActionStep.objects.create(action=action_user_paid, event="user paid")
        Person.objects.create(distinct_ids=["user_paid"], team=self.team)
        event = Event.objects.create(event="user paid", distinct_id="user_paid", team=self.team)
        self.assertEqual(event.actions, [action_user_paid])

    def test_element_class_set_to_none(self):
        action_user_paid = Action.objects.create(team=self.team, name="user paid")
        ActionStep.objects.create(action=action_user_paid, selector="a.something")
        Person.objects.create(distinct_ids=["user_paid"], team=self.team)
        event = Event.objects.create(
            event="$autocapture",
            distinct_id="user_paid",
            team=self.team,
            elements=[Element(tag_name="a", attr_class=None)],
        )
        # This would error when attr_class wasn't set.
        self.assertEqual(event.actions, [])


class TestPreCalculation(BaseTest):
    def test_update_or_delete_action_steps(self):
        user_signed_up = Event.objects.create(event="user signed up", team=self.team)
        user_logged_in = Event.objects.create(event="user logged in", team=self.team)
        user_logged_out = Event.objects.create(event="user logged out", team=self.team)
        action = Action.objects.create(team=self.team, name="combined action")
        step1 = ActionStep.objects.create(action=action, event="user signed up")
        step2 = ActionStep.objects.create(action=action, event="user logged in")
        with self.assertNumQueries(6):
            action.calculate_events()
        self.assertEqual(
            [e for e in action.events.all().order_by("id")], [user_signed_up, user_logged_in],
        )

        # update actionstep
        step2.event = "user logged out"
        step2.save()
        with self.assertNumQueries(6):
            action.calculate_events()
        self.assertEqual(
            [e for e in action.events.all().order_by("id")], [user_signed_up, user_logged_out],
        )

        # delete actionstep
        ActionStep.objects.filter(pk=step2.pk).delete()
        action.calculate_events()
        self.assertEqual([e for e in action.events.all().order_by("id")], [user_signed_up])

        ActionStep.objects.all().delete()
        action.calculate_events()
        self.assertEqual([e for e in action.events.all().order_by("id")], [])

    def test_empty(self):
        Person.objects.create(team=self.team, distinct_ids=["person1"], properties={"$browser": "Chrome"})
        action = Action.objects.create(name="pageview", team=self.team)
        ActionStep.objects.create(
            action=action, event="$pageview", properties=[{"key": "$browser", "value": "Chrome", "type": "person"}],
        )
        action.calculate_events()
        self.assertEqual(action.events.count(), 0)


class TestSelectors(BaseTest):
    def test_selector_splitting(self):
        selector1 = Selector("div > span > a")
        selector2 = Selector("div span > a")
        selector3 = Selector("div span a")
        selector4 = Selector("div > span a")

        self.assertEqual(len(selector1.parts), 3)
        self.assertEqual(len(selector2.parts), 3)
        self.assertEqual(len(selector3.parts), 3)
        self.assertEqual(len(selector4.parts), 3)

    def test_selector_child(self):
        selector1 = Selector("div span")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, False)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_selector_child_direct_descendant(self):
        selector1 = Selector("div > span")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_selector_attribute(self):
        selector1 = Selector('div[data-id="5"] > span')

        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div", "attributes__attr__data-id": "5"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_selector_id(self):
        selector1 = Selector('[id="5"] > span')

        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"attr_id": "5"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_selector_attribute_with_spaces(self):
        selector1 = Selector('  [data-id="foo bar]"]  ')

        self.assertEqual(selector1.parts[0].data, {"attributes__attr__data-id": "foo bar]"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

    def test_selector_with_spaces(self):
        selector1 = Selector("span    ")

        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

    def test_class(self):
        selector1 = Selector("div.classone.classtwo > span")

        self.assertEqual(selector1.parts[0].data, {"tag_name": "span"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(
            selector1.parts[1].data, {"tag_name": "div", "attr_class__contains": ["classone", "classtwo"],}
        )
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_nth_child(self):
        selector1 = Selector("div > span:nth-child(3)")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "span", "nth_child": "3"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 0)

    def test_unique_order(self):
        selector1 = Selector("div > div")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, True)
        self.assertEqual(selector1.parts[1].unique_order, 1)

    def test_asterisk_in_query(self):
        # Sometimes people randomly add * but they don't do very much, so just remove them
        selector1 = Selector("div > *")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)
        self.assertEqual(len(selector1.parts), 1)

    def test_asterisk_in_middle_of_query(self):
        selector1 = Selector("div > * > div")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[0].direct_descendant, False)
        self.assertEqual(selector1.parts[0].unique_order, 0)

        self.assertEqual(selector1.parts[1].data, {"tag_name": "div"})
        self.assertEqual(selector1.parts[1].direct_descendant, False)
        self.assertEqual(selector1.parts[1].unique_order, 1)


class TestEventModel(BaseTest):
    def test_earliest_timestamp(self):
        with freeze_time("2012-01-15T02:44:00.000Z"):
            Event.objects.create(
                team=self.team, distinct_id="whatever",
            )

        with freeze_time("2012-01-14T03:21:34.000Z"):
            Event.objects.create(
                team=self.team, distinct_id="whatever",
            )

        with freeze_time("2012-01-16T03:21:34.000Z"):
            self.assertEqual(Event.objects.earliest_timestamp(self.team.id), "2012-01-14T00:00:00+00:00")
            # Team has no events
            self.assertEqual(Event.objects.earliest_timestamp(team_id=-1), "2012-01-09T00:00:00+00:00")
