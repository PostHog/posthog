import re

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Element, Organization
from posthog.models.element.element import elements_to_string
from posthog.models.event import Selector
from posthog.models.property.util import build_selector_regex

from products.actions.backend.models.action import Action


def _create_action(team, steps):
    return Action.objects.create(team=team, steps_json=steps)


# :TODO: Move ee/clickhouse/models/test/test_action.py here
def filter_by_actions_factory(_create_event, _create_person, _get_events_for_action):
    class TestFilterByActions(BaseTest):
        def test_filter_with_selector_direct_decendant_ordering(self):
            all_events = self._setup_action_selector_events()
            action = _create_action(
                self.team,
                [
                    {"event": "$autocapture", "selector": "div > div > a"},
                    {
                        "event": "$autocapture",
                        "selector": "div > a.somethingthatdoesntexist",
                    },
                ],
            )

            self.assertActionEventsMatch(action, [all_events[1]])

        def test_filter_with_selector_nth_child(self):
            all_events = self._setup_action_selector_events()
            action = _create_action(
                self.team,
                [{"event": "$autocapture", "selector": "div > a:nth-child(2)"}],
            )

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
                    Element(
                        tag_name="a",
                        href="/a-url",
                        nth_child=1,
                        nth_of_type=0,
                        attr_class=["one-class"],
                    ),
                    Element(tag_name="button", nth_child=0, nth_of_type=0),
                    Element(
                        # Important that in this hierarchy the div is sandwiched between button and section.
                        # This way makes sure that any conditions which should match this element also work
                        # if the element is neither first nor last in the hierarchy.
                        tag_name="div",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                    Element(tag_name="section", nth_child=0, nth_of_type=0, attr_id="nested"),
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

            self.assertCountEqual([e.uuid for e in events], list(expected_events))

        def test_with_normal_filters(self):
            # this test also specifically tests the back to back receipt of
            # the same type of events by action to test the query cache
            _create_person(distinct_ids=["whatever"], team=self.team)
            # _create_person(distinct_ids=["whatever2"], team=self.team)

            action1 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {"event": "$autocapture", "href": "/a-url", "selector": "a"},
                    {"event": "$autocapture", "href": "/a-url-2"},
                ],
            )

            team2 = Organization.objects.bootstrap(None)[2]
            event1_uuid = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever",
                elements=[
                    Element(
                        tag_name="a",
                        href="/a-url",
                        text="some_text",
                        nth_child=0,
                        nth_of_type=0,
                    )
                ],
            )

            event2_uuid = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[
                    Element(
                        tag_name="a",
                        href="/a-url",
                        text="some_text",
                        nth_child=0,
                        nth_of_type=0,
                    )
                ],
            )

            event3_uuid = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever",
                elements=[
                    Element(
                        tag_name="a",
                        href="/a-url-2",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(
                        tag_name="div",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                ],
            )

            event4_uuid = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[
                    Element(
                        tag_name="a",
                        href="/a-url-2",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(
                        tag_name="div",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                ],
            )

            # team leakage
            _create_event(
                team=team2,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[
                    Element(
                        tag_name="a",
                        href="/a-url",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    )
                ],
            )
            _create_event(
                team=team2,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[
                    Element(
                        tag_name="a",
                        href="/a-url-2",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    )
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 4)
            self.assertEqual(events[0].uuid, event4_uuid)
            self.assertEqual(events[1].uuid, event3_uuid)
            self.assertEqual(events[2].uuid, event2_uuid)
            self.assertEqual(events[3].uuid, event1_uuid)

        def test_with_href_contains(self):
            _create_person(distinct_ids=["whatever"], team=self.team)

            action1 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "href": "/a-url",
                        "href_matching": "contains",
                        "selector": "a",
                    }
                ],
            )

            event1_uuid = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever",
                elements=[
                    Element(
                        tag_name="a",
                        href="/a-url",
                        text="some_text",
                        nth_child=0,
                        nth_of_type=0,
                    )
                ],
            )

            event2_uuid = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[
                    Element(
                        tag_name="a",
                        href="https://google.com/a-url",
                        text="some_text",
                        nth_child=0,
                        nth_of_type=0,
                    )
                ],
            )

            event3_uuid = _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="whatever",
                elements=[
                    Element(
                        tag_name="a",
                        href="/a-url-2",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(
                        tag_name="div",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                ],
            )

            _create_event(  # Not matched because href is /b-url not /a-url
                team=self.team,
                event="$autocapture",
                distinct_id="whatever2",
                elements=[
                    Element(
                        tag_name="a",
                        href="/b-url",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(
                        tag_name="div",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    ),
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 3)
            self.assertEqual(events[0].uuid, event3_uuid)
            self.assertEqual(events[1].uuid, event2_uuid)
            self.assertEqual(events[2].uuid, event1_uuid)

        def test_with_class(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "selector": "a.nav-link.active",
                        "tag_name": "a",
                    }
                ],
            )
            event1_uuid = _create_event(
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
                elements=[
                    Element(tag_name="span", attr_class=None),
                    Element(tag_name="a", attr_class=None),
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(events[0].uuid, event1_uuid)
            self.assertEqual(len(events), 1)

        def test_with_class_with_escaped_symbols(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "selector": "a.na\\v-link:b@ld",
                        "tag_name": "a",
                    }
                ],
            )
            event1_uuid = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="span", attr_class=None),
                    Element(tag_name="a", attr_class=["na\\v-link:b@ld"]),
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(events[0].uuid, event1_uuid)
            self.assertEqual(len(events), 1)

        def test_with_class_with_escaped_slashes(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "selector": "a.na\\\\\\v-link:b@ld",
                        "tag_name": "a",
                    }
                ],
            )
            event1_uuid = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="span", attr_class=None),
                    Element(tag_name="a", attr_class=["na\\\\\\v-link:b@ld"]),
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(events[0].uuid, event1_uuid)
            self.assertEqual(len(events), 1)

        def test_with_tag_matching_class_selector(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "selector": "input",  # This should ONLY match the tag, but not a class named `input`
                    }
                ],
            )
            event_matching_tag_uuid = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="span", attr_class=None),
                    Element(tag_name="input", attr_class=["button"]),  # Should match
                ],
            )
            _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[
                    Element(tag_name="span", attr_class=None),
                    Element(tag_name="button", attr_class=["input"]),  # Cannot match
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].uuid, event_matching_tag_uuid)

        def test_attributes(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            event1_uuid = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[Element(tag_name="button", attributes={"attr__data-id": "123"})],
            )

            action1 = Action.objects.create(
                team=self.team, steps_json=[{"event": "$autocapture", "selector": '[data-id="123"]'}]
            )

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].uuid, event1_uuid)

        def test_filter_events_by_url(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action1 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "url": "https://posthog.com/feedback/123",
                        "url_matching": "exact",
                    },
                    {"event": "$autocapture", "href": "/a-url-2"},
                ],
            )

            action2 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "url": "123",
                        "url_matching": "contains",
                    }
                ],
            )

            action3 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "url": "https://posthog.com/%/123",
                        "url_matching": "contains",
                    }
                ],
            )

            action4 = Action.objects.create(
                team=self.team,
                steps_json=[
                    {
                        "event": "$autocapture",
                        "url": "/123$",
                        "url_matching": "regex",
                    }
                ],
            )

            _create_event(team=self.team, distinct_id="whatever", event="$autocapture")
            event2_uuid = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                properties={"$current_url": "https://posthog.com/feedback/123"},
                elements=[
                    Element(
                        tag_name="div",
                        text="some_other_text",
                        nth_child=0,
                        nth_of_type=0,
                    )
                ],
            )

            events = _get_events_for_action(action1)
            self.assertEqual(events[0].uuid, event2_uuid)
            self.assertEqual(len(events), 1)

            events = _get_events_for_action(action2)
            self.assertEqual(events[0].uuid, event2_uuid)
            self.assertEqual(len(events), 1)

            events = _get_events_for_action(action3)
            self.assertEqual(events[0].uuid, event2_uuid)
            self.assertEqual(len(events), 1)

            events = _get_events_for_action(action4)
            self.assertEqual(events[0].uuid, event2_uuid)
            self.assertEqual(len(events), 1)

        def test_person_with_different_distinct_id(self):
            action_watch_movie = Action.objects.create(
                team=self.team,
                name="watched movie",
                steps_json=[
                    {
                        "tag_name": "a",
                        "href": "/movie",
                        "event": "$autocapture",
                    }
                ],
            )

            _create_person(distinct_ids=["anonymous_user", "is_now_signed_up"], team=self.team)
            _create_event(
                distinct_id="anonymous_user",
                team=self.team,
                elements=[Element(tag_name="a", href="/movie")],
                event="$autocapture",
            )

            event_watched_movie_uuid = _create_event(
                distinct_id="is_now_signed_up",
                team=self.team,
                elements=[Element(tag_name="a", href="/movie")],
                event="$autocapture",
            )

            events = _get_events_for_action(action_watch_movie)
            self.assertEqual(events[0].uuid, event_watched_movie_uuid)
            self.assertEqual(events[0].distinct_id, "is_now_signed_up")

        def test_no_person_leakage_from_other_teams(self):
            action_watch_movie = Action.objects.create(
                team=self.team, name="watched movie", steps_json=[{"event": "user signed up"}]
            )

            _create_person(distinct_ids=["anonymous_user"], team=self.team)
            _create_event(event="user signed up", distinct_id="anonymous_user", team=self.team)

            team2 = Organization.objects.bootstrap(None)[2]
            _create_person(distinct_ids=["anonymous_user2"], team=team2)

            events = _get_events_for_action(action_watch_movie)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].distinct_id, "anonymous_user")

        def test_person_property(self):
            _create_person(
                team=self.team,
                distinct_ids=["person1"],
                properties={"$browser": "Chrome"},
            )
            _create_person(team=self.team, distinct_ids=["person2"])
            _create_event(event="$pageview", distinct_id="person1", team=self.team)
            _create_event(event="$pageview", distinct_id="person2", team=self.team)
            action = Action.objects.create(
                name="pageview",
                team=self.team,
                steps_json=[
                    {
                        "event": "$pageview",
                        "properties": [{"key": "$browser", "value": "Chrome", "type": "person"}],
                    }
                ],
            )
            events = _get_events_for_action(action)
            self.assertEqual(len(events), 1)

        def test_no_steps(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[Element(tag_name="button", attributes={"attr__data-id": "123"})],
            )
            action1 = Action.objects.create(team=self.team)

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 0)

        def test_empty_selector_same_as_null(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            action_null_selector = Action.objects.create(
                team=self.team, steps_json=[{"event": "$autocapture", "selector": None}]
            )
            action_empty_selector = Action.objects.create(
                team=self.team, steps_json=[{"event": "$autocapture", "selector": ""}]
            )
            event1_uuid = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[Element(tag_name="span", attr_class=None)],
            )

            events_null_selector = _get_events_for_action(action_null_selector)
            self.assertEqual(events_null_selector[0].uuid, event1_uuid)
            self.assertEqual(len(events_null_selector), 1)

            events_empty_selector = _get_events_for_action(action_empty_selector)
            self.assertEqual(events_empty_selector, events_null_selector)

    return TestFilterByActions


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

        self.assertEqual(
            selector1.parts[1].data,
            {"tag_name": "div", "attributes__attr__data-id": "5"},
        )
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
            selector1.parts[1].data,
            {"tag_name": "div", "attr_class__contains": ["classone", "classtwo"]},
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

    def test_slash_colon(self):
        # Make sure we strip these for full text search to work in the database
        selector1 = Selector("div#root\\:id")
        self.assertEqual(selector1.parts[0].data, {"tag_name": "div", "attr_id": "root:id"})


class TestSelectorRegexMatching(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a sibling class the selector does not name can carry any character",
                ".flex",
                [Element(tag_name="div", attr_class=["flex", "w-1/2", "!mt-0", "hover:bg-blue-500/75"])],
                True,
            ),
            (
                "a target class can carry slashes and bangs",
                ".bg-yellow/50",
                [Element(tag_name="div", attr_class=["bg-yellow/50"])],
                True,
            ),
            (
                "a tailwind arbitrary-value target class",
                ".max-w-[1045px]",
                [Element(tag_name="div", attr_class=["max-w-[1045px]"])],
                True,
            ),
            (
                "an attribute value with a pre-escaped quote",
                'div[title="say \\"hi\\""]',
                [Element(tag_name="div", attributes={"attr__title": 'say "hi"'})],
                True,
            ),
            (
                "a single-quoted attribute value containing double quotes",
                "div[title='say \"hi\"']",
                [Element(tag_name="div", attributes={"attr__title": 'say "hi"'})],
                True,
            ),
            (
                "a neighboring attribute value containing a quote",
                'div[title="hi"]',
                [Element(tag_name="div", attributes={"attr__data-x": 'a"b', "attr__title": "hi"})],
                True,
            ),
            (
                "a semicolon inside an attribute value stays inside the element",
                'input[type="text"]',
                [
                    Element(
                        tag_name="input", attributes={"attr__style": "display: flex; gap: 4px", "attr__type": "text"}
                    )
                ],
                True,
            ),
            (
                "attribute value mismatch",
                'div[title="hi"]',
                [Element(tag_name="div", attributes={"attr__title": "bye"})],
                False,
            ),
            (
                "class not on the element",
                ".flex",
                [Element(tag_name="div", attr_class=["lex"])],
                False,
            ),
            (
                "direct child combinator still matches parent and child",
                "a > b",
                [Element(tag_name="b"), Element(tag_name="a")],
                True,
            ),
            (
                "descendant combinator still matches parent and child",
                "a b",
                [Element(tag_name="b"), Element(tag_name="a")],
                True,
            ),
            (
                "direct child combinator does not match the reversed order",
                "a > b",
                [Element(tag_name="a"), Element(tag_name="b")],
                False,
            ),
        ]
    )
    def test_selector_matches_elements_chain(self, _name, selector, elements, expected):
        regex = build_selector_regex(Selector(selector, escape_slashes=False))
        self.assertEqual(bool(re.search(regex, elements_to_string(elements))), expected)


class TestSelectorRegexMonotonicity(SimpleTestCase):
    SELECTORS = [
        ".flex",
        ".class",
        ".bg-yellow/50",
        ".!ml-auto",
        ".max-w-[1045px]",
        "div",
        "a > b",
        "a b",
        'div[title="say \\"hi\\""]',
        "div[title='say \"hi\"']",
        'a[href="/pricing"]',
        '[id="submit"]',
        "button.btn:nth-child(3)",
    ]

    ELEMENT_CHAINS = [
        [Element(tag_name="div", attr_class=["flex", "w-1/2"])],
        [Element(tag_name="div", attr_class=["bg-yellow/50", "!ml-auto"])],
        [Element(tag_name="div", attr_class=["max-w-[1045px]", "shadow-[0_4px_6px_rgba(0,0,0,0.1)]"])],
        [Element(tag_name="div", attr_class=["class"], attributes={"attr__title": 'say "hi"'})],
        [Element(tag_name="input", attributes={"attr__style": "display: flex; gap: 4px", "attr__type": "text"})],
        [Element(tag_name="b"), Element(tag_name="a")],
        [Element(tag_name="b"), Element(tag_name="div"), Element(tag_name="a")],
        [Element(tag_name="a", href="/pricing", attr_class=["px-2", "hover:underline"])],
        [Element(tag_name="button", attr_class=["btn"], nth_child=3), Element(tag_name="form")],
        [Element(tag_name="button", attr_id="submit", attributes={"attr__type": "button"})],
        # an attribute value that itself looks like a class followed by more text,
        # which the old tail could wander into
        [Element(tag_name="span", attributes={"attr__title": "x.class y"})],
    ]

    @staticmethod
    def _pre_fix_build_selector_regex(selector: Selector) -> str:
        # Frozen copy of build_selector_regex from before the tail and
        # quote-escaping fix, kept to prove the fix only widens matching.
        regex = r""
        for tag in selector.parts:
            if tag.data.get("tag_name") and isinstance(tag.data["tag_name"], str) and tag.data["tag_name"] != "*":
                regex += re.escape(tag.data["tag_name"])
            if tag.data.get("attr_class__contains"):
                regex += r".*?\." + r"\..*?".join([re.escape(s) for s in sorted(tag.data["attr_class__contains"])])
            if tag.ch_attributes:
                regex += r".*?"
                for key, value in sorted(tag.ch_attributes.items()):
                    regex += rf'{re.escape(key)}="{re.escape(str(value))}".*?'
            regex += r'([-_a-zA-Z0-9\.:"= \[\]\(\),]*?)?($|;|:([^;^\s]*(;|$|\s)))'
            if tag.direct_descendant:
                regex += r".*"
        return r"(^|;)" + regex if regex else r""

    def test_fix_only_widens_matching(self):
        chains = [elements_to_string(elements) for elements in self.ELEMENT_CHAINS]
        newly_matching_pairs = 0
        for selector_string in self.SELECTORS:
            selector = Selector(selector_string, escape_slashes=False)
            old_regex = self._pre_fix_build_selector_regex(selector)
            new_regex = build_selector_regex(selector)
            for chain in chains:
                old_match = bool(re.search(old_regex, chain))
                new_match = bool(re.search(new_regex, chain))
                with self.subTest(selector=selector_string, chain=chain):
                    if old_match:
                        self.assertTrue(new_match)
                if new_match and not old_match:
                    newly_matching_pairs += 1
        # the corpus has to exercise the widening, or the superset check is vacuous
        self.assertGreater(newly_matching_pairs, 0)
