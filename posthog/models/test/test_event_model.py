from posthog.models import Action, ActionStep, Element, Organization
from posthog.models.event import Selector
from posthog.test.base import BaseTest


def _create_action(team, steps):
    action = Action.objects.create(team=team)
    for step in steps:
        ActionStep.objects.create(action=action, **step)

    return action


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
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested"),
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

            self.assertCountEqual([e.uuid for e in events], [event_uuid for event_uuid in expected_events])

        def test_with_normal_filters(self):
            # this test also specifically tests the back to back receipt of
            # the same type of events by action to test the query cache
            _create_person(distinct_ids=["whatever"], team=self.team)
            # _create_person(distinct_ids=["whatever2"], team=self.team)

            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(event="$autocapture", action=action1, href="/a-url", selector="a")
            ActionStep.objects.create(event="$autocapture", action=action1, href="/a-url-2")

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

            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture",
                action=action1,
                href="/a-url",
                href_matching="contains",
                selector="a",
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
            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture",
                action=action1,
                selector="a.nav-link.active",
                tag_name="a",
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
            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture",
                action=action1,
                selector="a.na\\v-link:b@ld",
                tag_name="a",
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
            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture",
                action=action1,
                selector="a.na\\\\\\v-link:b@ld",
                tag_name="a",
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

        def test_attributes(self):
            _create_person(distinct_ids=["whatever"], team=self.team)
            event1_uuid = _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id="whatever",
                elements=[Element(tag_name="button", attributes={"attr__data-id": "123"})],
            )

            action1 = Action.objects.create(team=self.team)
            ActionStep.objects.create(event="$autocapture", action=action1, selector='[data-id="123"]')

            events = _get_events_for_action(action1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].uuid, event1_uuid)

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
            ActionStep.objects.create(
                event="$autocapture",
                action=action2,
                url="123",
                url_matching=ActionStep.CONTAINS,
            )

            action3 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture",
                action=action3,
                url="https://posthog.com/%/123",
                url_matching=ActionStep.CONTAINS,
            )

            action4 = Action.objects.create(team=self.team)
            ActionStep.objects.create(
                event="$autocapture",
                action=action4,
                url="/123$",
                url_matching=ActionStep.REGEX,
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
            action_watch_movie = Action.objects.create(team=self.team, name="watched movie")
            ActionStep.objects.create(
                action=action_watch_movie,
                tag_name="a",
                href="/movie",
                event="$autocapture",
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
            action_watch_movie = Action.objects.create(team=self.team, name="watched movie")
            ActionStep.objects.create(action=action_watch_movie, event="user signed up")

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
            action = Action.objects.create(name="pageview", team=self.team)
            ActionStep.objects.create(
                action=action,
                event="$pageview",
                properties=[{"key": "$browser", "value": "Chrome", "type": "person"}],
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
            action_null_selector = Action.objects.create(team=self.team)
            ActionStep.objects.create(action=action_null_selector, event="$autocapture", selector=None)
            action_empty_selector = Action.objects.create(team=self.team)
            ActionStep.objects.create(action=action_empty_selector, event="$autocapture", selector="")
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
