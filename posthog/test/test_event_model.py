from unittest.mock import call, patch

from posthog.api.test.base import BaseTest
from posthog.models import Action, ActionStep, Element, ElementGroup, Event, Person, Team
from posthog.models.event import Selector, SelectorPart


class TestFilterByActions(BaseTest):
    def test_filter_with_selectors(self):
        Person.objects.create(distinct_ids=["whatever"], team=self.team)

        event1 = Event.objects.create(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            elements=[
                Element(tag_name="a", href="/a-url", nth_child=1, nth_of_type=0, order=1),
                Element(tag_name="button", nth_child=0, nth_of_type=0, order=2),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=3),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=4, attr_id="nested",),
            ],
        )

        event2 = Event.objects.create(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            elements=[
                Element(tag_name="a", nth_child=2, nth_of_type=0, order=0, attr_id="someId"),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=1),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=2),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=3),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=4),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=5),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=6),
                # make sure elements don't get double counted if they're part of the same event
                Element(href="/a-url-2", nth_child=0, nth_of_type=0, order=7),
            ],
        )

        # make sure other teams' data doesn't get mixed in
        team2 = Team.objects.create()
        event3 = Event.objects.create(
            event="$autocapture",
            team=team2,
            distinct_id="whatever",
            elements=[
                Element(tag_name="a", nth_child=2, nth_of_type=0, order=0, attr_id="someId"),
                Element(tag_name="div", nth_child=0, nth_of_type=0, order=1),
            ],
        )

        # test direct decendant ordering
        action1 = Action.objects.create(team=self.team, name="action1")
        ActionStep.objects.create(event="$autocapture", action=action1, selector="div > div > a")
        ActionStep.objects.create(
            event="$autocapture", action=action1, selector="div > a.somethingthatdoesntexist",
        )
        action1.calculate_events()

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event2)

        # test :nth-child()
        action2 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action2, selector="div > a:nth-child(2)")
        action2.calculate_events()

        events = Event.objects.filter_by_action(action2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event2)

        # test [id='someId']
        action3 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action3, selector="[id='someId']")
        action3.calculate_events()

        events = Event.objects.filter_by_action(action3)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event2)

        # test selector without >
        action4 = Action.objects.create(team=self.team, name="action1")
        ActionStep.objects.create(event="$autocapture", action=action4, selector="[id='nested'] a")
        action4.calculate_events()

        events = Event.objects.filter_by_action(action4)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event1)

    def test_with_normal_filters(self):
        # this test also specifically tests the back to back receipt of
        # the same type of events by action to test the query cache
        Person.objects.create(distinct_ids=["whatever"], team=self.team)

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, href="/a-url", tag_name="a")
        ActionStep.objects.create(action=action1, href="/a-url-2")

        event1 = Event.objects.create(
            team=self.team,
            distinct_id="whatever",
            elements=[Element(tag_name="a", href="/a-url", text="some_text", nth_child=0, nth_of_type=0, order=0,)],
        )

        event2 = Event.objects.create(
            team=self.team,
            distinct_id="whatever2",
            elements=[Element(tag_name="a", href="/a-url", text="some_text", nth_child=0, nth_of_type=0, order=0,)],
        )

        event3 = Event.objects.create(
            team=self.team,
            distinct_id="whatever",
            elements=[
                Element(tag_name="a", href="/a-url-2", text="some_other_text", nth_child=0, nth_of_type=0, order=0,),
                # make sure elements don't get double counted if they're part of the same event
                Element(tag_name="div", text="some_other_text", nth_child=0, nth_of_type=0, order=1,),
            ],
        )

        event4 = Event.objects.create(
            team=self.team,
            distinct_id="whatever2",
            elements=[
                Element(tag_name="a", href="/a-url-2", text="some_other_text", nth_child=0, nth_of_type=0, order=0,),
                # make sure elements don't get double counted if they're part of the same event
                Element(tag_name="div", text="some_other_text", nth_child=0, nth_of_type=0, order=1,),
            ],
        )

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event4)
        self.assertEqual(events[1], event3)
        self.assertEqual(events[2], event2)
        self.assertEqual(events[3], event1)
        self.assertEqual(len(events), 4)

    def test_with_class(self):
        Person.objects.create(distinct_ids=["whatever"], team=self.team)
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, selector="a.nav-link.active", tag_name="a")
        event1 = Event.objects.create(
            team=self.team,
            distinct_id="whatever",
            elements=[
                Element(tag_name="span", attr_class=None, order=0),
                Element(tag_name="a", attr_class=["active", "nav-link"], order=1),
            ],
        )

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event1)
        self.assertEqual(len(events), 1)

    def test_attributes(self):
        Person.objects.create(distinct_ids=["whatever"], team=self.team)

        event1 = Event.objects.create(
            team=self.team,
            distinct_id="whatever",
            elements=[
                Element(tag_name="span", order=0),
                Element(tag_name="a", order=1, attributes={"data-id": "123"}),
            ],
        )

        event2 = Event.objects.create(
            team=self.team,
            distinct_id="whatever",
            elements=[Element(tag_name="button", order=0, attributes={"data-id": "123"})],
        )

        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action1, selector='a[data-id="123"]')
        action1.calculate_events()

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], event1)

    def test_filter_events_by_url(self):
        Person.objects.create(distinct_ids=["whatever"], team=self.team)
        action1 = Action.objects.create(team=self.team)
        ActionStep.objects.create(
            action=action1, url="https://posthog.com/feedback/123", url_matching=ActionStep.EXACT,
        )
        ActionStep.objects.create(action=action1, href="/a-url-2")

        action2 = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action2, url="123", url_matching=ActionStep.CONTAINS)

        action3 = Action.objects.create(team=self.team)
        ActionStep.objects.create(
            action=action3, url="https://posthog.com/%/123", url_matching=ActionStep.CONTAINS,
        )

        action4 = Action.objects.create(team=self.team)
        ActionStep.objects.create(
            action=action4, url="/123$", url_matching=ActionStep.REGEX,
        )

        event1 = Event.objects.create(team=self.team, distinct_id="whatever")
        event2 = Event.objects.create(
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123"},
            elements=[Element(tag_name="div", text="some_other_text", nth_child=0, nth_of_type=0, order=1,)],
        )

        events = Event.objects.filter_by_action(action1)
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

        events = Event.objects.filter_by_action(action2)
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

        events = Event.objects.filter_by_action(action3)
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

        events = Event.objects.filter_by_action(action4)
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

    def test_person_with_different_distinct_id(self):
        action_watch_movie = Action.objects.create(team=self.team, name="watched movie")
        ActionStep.objects.create(action=action_watch_movie, tag_name="a", href="/movie")

        person = Person.objects.create(distinct_ids=["anonymous_user", "is_now_signed_up"], team=self.team)
        event_watched_movie_anonymous = Event.objects.create(
            distinct_id="anonymous_user", team=self.team, elements=[Element(tag_name="a", href="/movie")],
        )

        event_watched_movie = Event.objects.create(
            distinct_id="is_now_signed_up", team=self.team, elements=[Element(tag_name="a", href="/movie")],
        )

        events = Event.objects.filter_by_action(action_watch_movie)
        self.assertEqual(events[0], event_watched_movie)
        self.assertEqual(events[0].person_id, person.pk)

    def test_no_person_leakage_from_other_teams(self):
        action_watch_movie = Action.objects.create(team=self.team, name="watched movie")
        ActionStep.objects.create(action=action_watch_movie, event="user signed up")

        person = Person.objects.create(distinct_ids=["anonymous_user"], team=self.team)
        event_watched_movie_anonymous = Event.objects.create(
            event="user signed up", distinct_id="anonymous_user", team=self.team
        )

        team2 = Team.objects.create()
        person2 = Person.objects.create(distinct_ids=["anonymous_user"], team=team2)

        events = Event.objects.filter_by_action(action_watch_movie)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].person_id, person.pk)


class TestElementGroup(BaseTest):
    def test_create_elements(self):
        elements = [
            Element(tag_name="button", text="Sign up!"),
            Element(tag_name="div"),
        ]
        group1 = ElementGroup.objects.create(team=self.team, elements=elements)
        elements = list(Element.objects.all())
        self.assertEqual(elements[0].tag_name, "button")
        self.assertEqual(elements[1].tag_name, "div")

        elements = [
            Element(tag_name="button", text="Sign up!"),
            # make sure we remove events if we can
            Element(tag_name="div", event=Event.objects.create(team=self.team)),
        ]
        group2 = ElementGroup.objects.create(team=self.team, elements=elements)
        self.assertEqual(Element.objects.count(), 2)
        self.assertEqual(group1.hash, group2.hash)

        # Test no team leakage
        team2 = Team.objects.create()
        group3 = ElementGroup.objects.create(team=team2, elements=elements)
        group3_duplicate = ElementGroup.objects.create(team_id=team2.pk, elements=elements)
        self.assertNotEqual(group2, group3)
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
                    order=0,
                ),
                Element(tag_name="div", href="/movie", order=1),
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
            elements=[Element(order=0, tag_name="a", attributes={"data-id": "whatever"})],
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
            elements=[Element(tag_name="a", attr_class=None, order=0)],
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

    def test_save_with_person_property(self):
        Person.objects.create(team=self.team, distinct_ids=["person1"], properties={"$browser": "Chrome"})
        Event.objects.create(event="$pageview", distinct_id="person1", team=self.team)
        action = Action.objects.create(name="pageview", team=self.team)
        ActionStep.objects.create(
            action=action, event="$pageview", properties=[{"key": "$browser", "value": "Chrome", "type": "person"}],
        )
        action.calculate_events()
        self.assertEqual(action.events.count(), 1)

    def test_empty(self):
        Person.objects.create(team=self.team, distinct_ids=["person1"], properties={"$browser": "Chrome"})
        action = Action.objects.create(name="pageview", team=self.team)
        ActionStep.objects.create(
            action=action, event="$pageview", properties=[{"key": "$browser", "value": "Chrome", "type": "person"}],
        )
        action.calculate_events()
        self.assertEqual(action.events.count(), 0)


class TestSendToSlack(BaseTest):
    @patch("posthog.tasks.slack.post_event_to_slack.delay")
    def test_send_to_slack(self, patch_post_to_slack):
        self.team.slack_incoming_webhook = "http://slack.com/hook"
        action_user_paid = Action.objects.create(team=self.team, name="user paid", post_to_slack=True)
        ActionStep.objects.create(action=action_user_paid, event="user paid")

        event = Event.objects.create(team=self.team, event="user paid", site_url="http://testserver")
        self.assertEqual(patch_post_to_slack.call_count, 1)
        patch_post_to_slack.assert_has_calls([call(event.pk, "http://testserver")])


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
        self.assertEqual(
            selector1.parts[0].__dict__, {"data": {"tag_name": "span"}, "direct_descendant": False, "unique_order": 0,},
        )
        self.assertEqual(
            selector1.parts[1].__dict__, {"data": {"tag_name": "div"}, "direct_descendant": False, "unique_order": 0,},
        )

    def test_selector_child_direct_descendant(self):
        selector1 = Selector("div > span")
        self.assertEqual(
            selector1.parts[0].__dict__, {"data": {"tag_name": "span"}, "direct_descendant": False, "unique_order": 0,},
        )
        self.assertEqual(
            selector1.parts[1].__dict__, {"data": {"tag_name": "div"}, "direct_descendant": True, "unique_order": 0},
        )

    def test_selector_attribute(self):
        selector1 = Selector('div[data-id="5"] > span')
        self.assertEqual(
            selector1.parts[0].__dict__, {"data": {"tag_name": "span"}, "direct_descendant": False, "unique_order": 0,},
        )
        self.assertEqual(
            selector1.parts[1].__dict__,
            {"data": {"tag_name": "div", "attributes__data-id": "5"}, "direct_descendant": True, "unique_order": 0,},
        )

    def test_selector_id(self):
        selector1 = Selector('[id="5"] > span')
        self.assertEqual(
            selector1.parts[0].__dict__, {"data": {"tag_name": "span"}, "direct_descendant": False, "unique_order": 0,},
        )
        self.assertEqual(
            selector1.parts[1].__dict__, {"data": {"attr_id": "5"}, "direct_descendant": True, "unique_order": 0},
        )

    def test_class(self):
        selector1 = Selector("div.classone.classtwo > span")
        self.assertEqual(
            selector1.parts[0].__dict__, {"data": {"tag_name": "span"}, "direct_descendant": False, "unique_order": 0,},
        )
        self.assertEqual(
            selector1.parts[1].__dict__,
            {
                "data": {"tag_name": "div", "attr_class__contains": ["classone", "classtwo"],},
                "direct_descendant": True,
                "unique_order": 0,
            },
        )

    def test_nth_child(self):
        selector1 = Selector("div > span:nth-child(3)")
        self.assertEqual(
            selector1.parts[0].__dict__,
            {"data": {"tag_name": "span", "nth_child": "3"}, "direct_descendant": False, "unique_order": 0,},
        )
        self.assertEqual(
            selector1.parts[1].__dict__, {"data": {"tag_name": "div"}, "direct_descendant": True, "unique_order": 0},
        )

    def test_unique_order(self):
        selector1 = Selector("div > div")
        self.assertEqual(
            selector1.parts[0].__dict__, {"data": {"tag_name": "div"}, "direct_descendant": False, "unique_order": 0,},
        )
        self.assertEqual(
            selector1.parts[1].__dict__, {"data": {"tag_name": "div"}, "direct_descendant": True, "unique_order": 1},
        )
