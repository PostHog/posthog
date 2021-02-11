from unittest.mock import patch

from freezegun import freeze_time

from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models import Action, ActionStep, Element, Event, Person
from posthog.models.filters import Filter
from posthog.queries.abstract_test.test_interval import AbstractIntervalTest
from posthog.queries.abstract_test.test_timerange import AbstractTimerangeTest
from posthog.queries.funnel import Funnel
from posthog.tasks.update_cache import update_cache_item
from posthog.test.base import APIBaseTest, BaseTest


def funnel_test_factory(Funnel, event_factory, person_factory):
    @patch("posthog.celery.update_cache_item_task.delay", update_cache_item)
    class TestGetFunnel(BaseTest):
        TESTS_API = True

        def _signup_event(self, **kwargs):
            event_factory(team=self.team, event="user signed up", **kwargs)

        def _pay_event(self, **kwargs):
            event_factory(
                team=self.team,
                event="$autocapture",
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="button", text="Pay $10")],
                **kwargs
            )

        def _movie_event(self, **kwargs):
            event_factory(
                team=self.team,
                event="$autocapture",
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="a", href="/movie")],
                **kwargs
            )

        def _single_step_funnel(self, properties=None, filters=None):
            if filters is None:
                filters = {
                    "events": [{"id": "user signed up", "type": "events", "order": 0},],
                    "insight": INSIGHT_FUNNELS,
                }

            if properties is not None:
                filters.update({"properties": properties})

            filter = Filter(data=filters)
            return Funnel(filter=filter, team=self.team)

        def _basic_funnel(self, properties=None, filters=None):
            action_credit_card = Action.objects.create(team=self.team, name="paid")
            ActionStep.objects.create(
                action=action_credit_card, event="$autocapture", tag_name="button", text="Pay $10"
            )
            action_play_movie = Action.objects.create(team=self.team, name="watched movie")
            ActionStep.objects.create(action=action_play_movie, event="$autocapture", tag_name="a", href="/movie")

            if filters is None:
                filters = {
                    "events": [{"id": "user signed up", "type": "events", "order": 0},],
                    "actions": [
                        {"id": action_credit_card.pk, "type": "actions", "order": 1},
                        {"id": action_play_movie.pk, "type": "actions", "order": 2},
                    ],
                }

            if properties is not None:
                filters.update({"properties": properties})

            filters["insight"] = INSIGHT_FUNNELS
            filter = Filter(data=filters)
            return Funnel(filter=filter, team=self.team)

        def test_funnel_default(self):
            funnel = self._single_step_funnel()

            with freeze_time("2012-01-01T03:21:34.000Z"):
                # event
                person1_stopped_after_signup = person_factory(
                    distinct_ids=["stopped_after_signup1"], team_id=self.team.pk
                )
                self._signup_event(distinct_id="stopped_after_signup1")

                person2_stopped_after_signup = person_factory(
                    distinct_ids=["stopped_after_signup2"], team_id=self.team.pk
                )
                self._signup_event(distinct_id="stopped_after_signup2")

            with self.assertNumQueries(1):
                result = funnel.run()
            self.assertEqual(result[0]["count"], 0)

        def test_funnel_with_single_step(self):
            funnel = self._single_step_funnel()

            # event
            person1_stopped_after_signup = person_factory(distinct_ids=["stopped_after_signup1"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup1")

            person2_stopped_after_signup = person_factory(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup2")

            with self.assertNumQueries(1):
                result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 2)
            # check ordering of people in first step
            self.assertCountEqual(
                result[0]["people"], [person1_stopped_after_signup.uuid, person2_stopped_after_signup.uuid],
            )

        def test_funnel_events(self):
            funnel = self._basic_funnel()

            # events
            person_stopped_after_signup = person_factory(distinct_ids=["stopped_after_signup"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_signup")

            person_stopped_after_pay = person_factory(distinct_ids=["stopped_after_pay"], team_id=self.team.pk)
            self._signup_event(distinct_id="stopped_after_pay")
            self._pay_event(distinct_id="stopped_after_pay")

            person_stopped_after_movie = person_factory(
                distinct_ids=["had_anonymous_id", "completed_movie"], team_id=self.team.pk
            )
            self._signup_event(distinct_id="had_anonymous_id")
            self._pay_event(distinct_id="completed_movie")
            self._movie_event(distinct_id="completed_movie")

            person_that_just_did_movie = person_factory(distinct_ids=["just_did_movie"], team_id=self.team.pk)
            self._movie_event(distinct_id="just_did_movie")

            person_wrong_order = person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._pay_event(distinct_id="wrong_order")
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            self._signup_event(distinct_id="a_user_that_got_deleted_or_doesnt_exist")

            result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 4)
            # check ordering of people in first step
            self.assertCountEqual(
                result[0]["people"],
                [
                    person_stopped_after_movie.uuid,
                    person_stopped_after_pay.uuid,
                    person_stopped_after_signup.uuid,
                    person_wrong_order.uuid,
                ],
            )
            self.assertEqual(result[1]["name"], "paid")
            self.assertEqual(result[1]["count"], 2)
            self.assertEqual(result[2]["name"], "watched movie")
            self.assertEqual(result[2]["count"], 1)
            self.assertEqual(result[2]["people"], [person_stopped_after_movie.uuid])

            # make sure it's O(n)
            person_wrong_order = person_factory(distinct_ids=["badalgo"], team_id=self.team.pk)
            self._signup_event(distinct_id="badalgo")
            with self.assertNumQueries(3):
                funnel.run()

            self._pay_event(distinct_id="badalgo")
            with self.assertNumQueries(3):
                funnel.run()

        def test_funnel_no_events(self):
            funnel = Funnel(filter=Filter(data={"some": "prop"}), team=self.team)
            self.assertEqual(funnel.run(), [])

        def test_funnel_skipped_step(self):
            funnel = self._basic_funnel()

            person_wrong_order = person_factory(distinct_ids=["wrong_order"], team_id=self.team.pk)
            self._signup_event(distinct_id="wrong_order")
            self._movie_event(distinct_id="wrong_order")

            result = funnel.run()
            self.assertEqual(result[1]["count"], 0)
            self.assertEqual(result[2]["count"], 0)

        def test_funnel_prop_filters(self):
            funnel = self._basic_funnel(properties={"$browser": "Safari"})

            # events
            with_property = person_factory(distinct_ids=["with_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="with_property", properties={"$browser": "Safari"})

            # should not add a count
            without_property = person_factory(distinct_ids=["without_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="without_property")
            self._pay_event(distinct_id="without_property")

            # will add to first step
            half_property = person_factory(distinct_ids=["half_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="half_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="half_property")

            result = funnel.run()
            self.assertEqual(result[0]["count"], 2)
            self.assertEqual(result[1]["count"], 1)

        def test_funnel_prop_filters_per_entity(self):
            action_credit_card = Action.objects.create(team_id=self.team.pk, name="paid")
            ActionStep.objects.create(
                action=action_credit_card, event="$autocapture", tag_name="button", text="Pay $10"
            )
            action_play_movie = Action.objects.create(team_id=self.team.pk, name="watched movie")
            ActionStep.objects.create(action=action_play_movie, event="$autocapture", tag_name="a", href="/movie")
            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {"key": "$browser", "value": "Safari"},
                            {"key": "$browser", "operator": "is_not", "value": "Chrome"},
                        ],
                    },
                ],
                "actions": [
                    {
                        "id": action_credit_card.pk,
                        "type": "actions",
                        "order": 1,
                        "properties": [{"key": "$browser", "value": "Safari"}],
                    },
                    {
                        "id": action_play_movie.pk,
                        "type": "actions",
                        "order": 2,
                        "properties": [{"key": "$browser", "value": "Firefox"}],
                    },
                ],
            }
            funnel = self._basic_funnel(filters=filters)

            # events
            with_property = person_factory(
                distinct_ids=["with_property"], team_id=self.team.pk, properties={"$browser": "Safari"},
            )
            self._signup_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._pay_event(distinct_id="with_property", properties={"$browser": "Safari"})
            self._movie_event(distinct_id="with_property")

            # should not add a count
            without_property = person_factory(distinct_ids=["without_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="without_property")
            self._pay_event(distinct_id="without_property", properties={"$browser": "Safari"})

            # will add to first step
            half_property = person_factory(distinct_ids=["half_property"], team_id=self.team.pk)
            self._signup_event(distinct_id="half_property")
            self._pay_event(distinct_id="half_property")
            self._movie_event(distinct_id="half_property")

            result = funnel.run()

            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 0)

        def test_funnel_person_prop(self):
            action_credit_card = Action.objects.create(team_id=self.team.pk, name="paid")
            ActionStep.objects.create(
                action=action_credit_card, event="$autocapture", tag_name="button", text="Pay $10"
            )
            action_play_movie = Action.objects.create(team_id=self.team.pk, name="watched movie")
            ActionStep.objects.create(action=action_play_movie, event="$autocapture", tag_name="a", href="/movie")
            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [{"key": "email", "value": "hello@posthog.com", "type": "person"},],
                    },
                ],
                "actions": [
                    {"id": action_credit_card.pk, "type": "actions", "order": 1,},
                    {"id": action_play_movie.pk, "type": "actions", "order": 2,},
                ],
            }
            funnel = self._basic_funnel(filters=filters)

            # events
            with_property = person_factory(
                distinct_ids=["with_property"], team_id=self.team.pk, properties={"email": "hello@posthog.com"},
            )
            self._signup_event(distinct_id="with_property")
            self._pay_event(distinct_id="with_property")
            self._movie_event(distinct_id="with_property")

            result = funnel.run()
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 1)

        def test_funnel_multiple_actions(self):
            # we had an issue on clickhouse where multiple actions with different property filters would incorrectly grab only the last
            # properties.
            # This test prevents a regression
            person_factory(distinct_ids=["person1"], team_id=self.team.pk)
            event_factory(distinct_id="person1", event="event1", team=self.team)
            event_factory(distinct_id="person1", event="event2", properties={"test_prop": "a"}, team=self.team)

            action1 = Action.objects.create(team_id=self.team.pk, name="event2")
            ActionStep.objects.create(action=action1, event="event2", properties=[{"key": "test_prop", "value": "a"}])
            action1.calculate_events()
            action2 = Action.objects.create(team_id=self.team.pk, name="event2")
            ActionStep.objects.create(action=action2, event="event2", properties=[{"key": "test_prop", "value": "c"}])
            action2.calculate_events()

            result = Funnel(
                filter=Filter(
                    data={
                        "events": [{"id": "event1", "order": 0}],
                        "actions": [{"id": action1.pk, "order": 1,}, {"id": action2.pk, "order": 2,},],
                        "insight": INSIGHT_FUNNELS,
                    }
                ),
                team=self.team,
            ).run()
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(result[1]["count"], 1)
            self.assertEqual(result[2]["count"], 0)

    return TestGetFunnel


class TestFunnel(funnel_test_factory(Funnel, Event.objects.create, Person.objects.create)):  # type: ignore
    pass


@patch("posthog.celery.update_cache_item_task.delay", update_cache_item)
def funnel_trends_test_factory(Funnel, event_factory, person_factory):
    class TestFunnelTrends(AbstractTimerangeTest, AbstractIntervalTest, APIBaseTest):
        def _create_events(self):
            # test person created way before funnel events happened
            with freeze_time("2020-12-02T01:01:01.000Z"):
                dropped_1 = person_factory(distinct_ids=["dropped_1"], team=self.team)
            with freeze_time("2021-01-01T03:21:34.000Z"):
                dropped_2 = person_factory(distinct_ids=["dropped_2"], team=self.team)
                completed_1 = person_factory(distinct_ids=["completed_1"], team=self.team)
                across_days = person_factory(distinct_ids=["across_days"], team=self.team)
                event_factory(event="sign up", distinct_id="dropped_1", team=self.team)
                event_factory(event="sign up", distinct_id="dropped_2", team=self.team)
                event_factory(event="sign up", distinct_id="completed_1", team=self.team)
                event_factory(event="sign up", distinct_id="across_days", team=self.team)
            with freeze_time("2021-01-01T03:31:34.000Z"):
                event_factory(event="pay", distinct_id="completed_1", team=self.team)

            with freeze_time("2021-01-02T03:21:34.000Z"):
                dropped_3 = person_factory(distinct_ids=["dropped_3"], team=self.team)
                completed_2 = person_factory(distinct_ids=["completed_2"], team=self.team)
                event_factory(event="sign up", distinct_id="dropped_3", team=self.team)
                event_factory(event="sign up", distinct_id="completed_2", team=self.team)
            with freeze_time("2021-01-02T03:21:35.000Z"):
                event_factory(event="pay", distinct_id="completed_2", team=self.team)
                event_factory(event="pay", distinct_id="across_days", team=self.team)

        def _run(self, date_from=None, date_to=None, interval=None):
            self._create_events()
            return Funnel(
                team=self.team,
                filter=Filter(
                    data={
                        "insight": INSIGHT_FUNNELS,
                        "display": TRENDS_LINEAR,
                        "interval": interval if interval else "day",
                        "date_from": date_from,
                        **({"date_to": date_to} if date_to else {}),
                        "events": [{"id": "sign up", "order": 0}, {"id": "pay", "order": 1},],
                    }
                ),
            ).run()

        def test_one_step(self):
            self._create_events()
            with freeze_time("2021-01-02T04:00:00.000Z"):
                result = Funnel(
                    team=self.team,
                    filter=Filter(
                        data={
                            "insight": INSIGHT_FUNNELS,
                            "display": TRENDS_LINEAR,
                            "interval": "day",
                            "events": [{"id": "sign up", "order": 0}],
                        }
                    ),
                ).run()
            self.assertEqual(result[0]["data"], [0, 0, 0, 0, 0, 0, 0, 0])

        def test_all_time_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("all", interval="month")
            self.assertEqual(response[0]["data"][0], 33)
            self.assertEqual(response[0]["labels"][0], "Fri. 1 January")

        def test_custom_range_timerange(self):
            response = self._run("2020-12-01T00:00:00.000Z", "2021-01-02T00:00:00.000Z")
            # across_days not completed yet hence 25%
            self.assertEqual(response[0]["data"][31], 25)
            self.assertEqual(response[0]["labels"][31], "Fri. 1 January")

        def test_day_interval(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run()
            self.assertEqual(response[0]["data"], [0, 0, 0, 0, 0, 0, 25, 50])

        def test_hour_interval(self):
            with freeze_time("2021-01-02T04:20:01.000Z"):
                response = self._run(interval="hour")
            self.assertEqual(response[0]["data"][147], 25)
            self.assertEqual(response[0]["labels"][147], "Fri. 1 January, 03:00")

            self.assertEqual(response[0]["data"][171], 50)
            self.assertEqual(response[0]["labels"][171], "Sat. 2 January, 03:00")

        def test_interval_rounding(self):
            pass

        def test_last14days_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("-14d")
            self.assertEqual(response[0]["data"][13], 25)
            self.assertEqual(response[0]["labels"][13], "Fri. 1 January")

            self.assertEqual(response[0]["data"][14], 50)
            self.assertEqual(response[0]["labels"][14], "Sat. 2 January")

        def test_last24hours_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("-24h")
            self.assertEqual(response[0]["data"][1], 50)
            self.assertEqual(response[0]["labels"][1], "Sat. 2 January")

        def test_last30days_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("-30d")
            self.assertEqual(response[0]["data"][30], 50)
            self.assertEqual(response[0]["labels"][30], "Sat. 2 January")

        def test_last48hours_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("-24h")
            self.assertEqual(response[0]["data"][1], 50)
            self.assertEqual(response[0]["labels"][1], "Sat. 2 January")

        def test_last7days_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("-7d")
            self.assertEqual(response[0]["data"][7], 50)
            self.assertEqual(response[0]["labels"][7], "Sat. 2 January")

        def test_last90days_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("-90d")
            self.assertEqual(response[0]["data"][90], 50)
            self.assertEqual(response[0]["labels"][90], "Sat. 2 January")

        def test_minute_interval(self):
            with freeze_time("2021-01-02T04:00:01.000Z"):
                response = self._run("-1h", interval="minute")
            self.assertEqual(response[0]["data"][21], 50)
            self.assertEqual(response[0]["labels"][21], "Sat. 2 January, 03:21")

        def test_month_interval(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("-90d", interval="month")
            self.assertEqual(response[0]["data"][2], 33)
            self.assertEqual(response[0]["labels"][2], "Fri. 1 January")

        def test_previous_month_timerange(self):
            with freeze_time("2021-02-10T04:00:00.000Z"):
                response = self._run("-1mStart", "-1mEnd", interval="month")
            self.assertEqual(response[0]["data"][0], 33)
            self.assertEqual(response[0]["labels"][0], "Fri. 1 January")

        def test_this_month_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("mStart", interval="day")
            self.assertEqual(response[0]["data"][1], 50)
            self.assertEqual(response[0]["labels"][1], "Sat. 2 January")

        def test_today_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("dStart")
            self.assertEqual(response[0]["data"][0], 50)
            self.assertEqual(response[0]["labels"][0], "Sat. 2 January")

        def test_week_interval(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("dStart")
            self.assertEqual(response[0]["data"][0], 50)
            self.assertEqual(response[0]["labels"][0], "Sat. 2 January")

        def test_year_to_date_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("yStart")
            self.assertEqual(response[0]["data"][1], 50)
            self.assertEqual(response[0]["labels"][1], "Sat. 2 January")

        def test_yesterday_timerange(self):
            with freeze_time("2021-01-02T04:00:00.000Z"):
                response = self._run("-1d", "dStart")
            self.assertEqual(response[0]["data"][0], 25)
            self.assertEqual(response[0]["labels"][0], "Fri. 1 January")

    return TestFunnelTrends


class TestFunnelTrends(funnel_trends_test_factory(Funnel, Event.objects.create, Person.objects.create)):  # type: ignore
    pass
