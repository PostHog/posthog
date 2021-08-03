from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.test.base import APIBaseTest


def funnel_breakdown_test_factory(Funnel, FunnelPerson, _create_event, _create_person):
    class TestFunnelBreakdown(APIBaseTest):
        def _get_people_at_step(self, filter, funnel_step, breakdown_value=None):
            person_filter = filter.with_data({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
            result = FunnelPerson(person_filter, self.team)._exec_query()
            return [row[0] for row in result]

        def test_funnel_step_breakdown_event(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "$browser",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Chrome"},
                timestamp="2020-01-01T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Chrome"},
                timestamp="2020-01-01T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="buy",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Chrome"},
                timestamp="2020-01-01T15:00:00Z",
            )

            person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person2",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person2",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T16:00:00Z",
            )

            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person3",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T14:00:00Z",
            )

            result = funnel.run()
            self.assertEqual(
                result[0],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Chrome",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "order": 1,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 3600.0,
                        "median_conversion_time": 3600.0,
                        "breakdown": "Chrome",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "order": 2,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Chrome",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Chrome"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Chrome"), [person1.uuid])
            self.assertEqual(
                result[1],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person2.uuid, person3.uuid]
                        if Funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 2,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "order": 1,
                        "people": [person2.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Safari",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "order": 2,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                    },
                ],
            )

            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari"), [person2.uuid, person3.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Safari"), [person2.uuid])

        def test_funnel_step_breakdown_event_no_type(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown": "$browser",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Chrome"},
                timestamp="2020-01-01T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Chrome"},
                timestamp="2020-01-01T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="buy",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Chrome"},
                timestamp="2020-01-01T15:00:00Z",
            )

            person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person2",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person2",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T16:00:00Z",
            )

            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person3",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T14:00:00Z",
            )

            result = funnel.run()
            self.assertEqual(
                result[0],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Chrome",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "order": 1,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 3600.0,
                        "median_conversion_time": 3600.0,
                        "breakdown": "Chrome",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "order": 2,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Chrome",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Chrome"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Chrome"), [person1.uuid])
            self.assertEqual(
                result[1],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person2.uuid, person3.uuid]
                        if Funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 2,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "order": 1,
                        "people": [person2.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Safari",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "order": 2,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                    },
                ],
            )

            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari"), [person2.uuid, person3.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Safari"), [person2.uuid])

        def test_funnel_step_breakdown_person(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "person",
                "breakdown": "$browser",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk, properties={"$browser": "Chrome"})
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val"},
                timestamp="2020-01-01T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person1",
                properties={"key": "val"},
                timestamp="2020-01-01T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="buy",
                distinct_id="person1",
                properties={"key": "val"},
                timestamp="2020-01-01T15:00:00Z",
            )

            person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk, properties={"$browser": "Safari"})
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person2",
                properties={"key": "val"},
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person2",
                properties={"key": "val"},
                timestamp="2020-01-02T16:00:00Z",
            )

            result = funnel.run()
            self.assertEqual(
                result[0],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Chrome",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "order": 1,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 3600.0,
                        "median_conversion_time": 3600.0,
                        "breakdown": "Chrome",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "order": 2,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Chrome",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Chrome"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Chrome"), [person1.uuid])

            self.assertEqual(
                result[1],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person2.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "order": 1,
                        "people": [person2.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Safari",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "order": 2,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari"), [person2.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 3, "Safari"), [])

        def test_funnel_step_breakdown_limit(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "some_breakdown_val",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            for num in range(10):
                for i in range(num):
                    _create_person(distinct_ids=[f"person_{num}_{i}"], team_id=self.team.pk)
                    _create_event(
                        team=self.team,
                        event="sign up",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T12:00:00Z",
                    )
                    _create_event(
                        team=self.team,
                        event="play movie",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T13:00:00Z",
                    )
                    _create_event(
                        team=self.team,
                        event="buy",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T15:00:00Z",
                    )

            result = funnel.run()

            # assert that we give 5 at a time at most and that those values are the most popular ones
            breakdown_vals = sorted([res[0]["breakdown"] for res in result])
            self.assertEqual(["5", "6", "7", "8", "9"], breakdown_vals)

        def test_funnel_step_custom_breakdown_limit_with_nulls(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown_limit": 3,
                "breakdown": "some_breakdown_val",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            for num in range(5):
                for i in range(num):
                    _create_person(distinct_ids=[f"person_{num}_{i}"], team_id=self.team.pk)
                    _create_event(
                        team=self.team,
                        event="sign up",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T12:00:00Z",
                    )
                    _create_event(
                        team=self.team,
                        event="play movie",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T13:00:00Z",
                    )
                    _create_event(
                        team=self.team,
                        event="buy",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T15:00:00Z",
                    )

            # no breakdown value for this guy
            _create_person(distinct_ids=[f"person_null"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id=f"person_null",
                properties={"key": "val"},
                timestamp="2020-01-01T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id=f"person_null",
                properties={"key": "val"},
                timestamp="2020-01-01T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="buy",
                distinct_id=f"person_null",
                properties={"key": "val"},
                timestamp="2020-01-01T15:00:00Z",
            )

            result = funnel.run()

            breakdown_vals = sorted([res[0]["breakdown"] for res in result])
            self.assertEqual(["2", "3", "4"], breakdown_vals)
            # skipped 1 and '' because the limit was 3.

        def test_funnel_step_custom_breakdown_limit_with_nulls_included(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown_limit": 6,
                "breakdown": "some_breakdown_val",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            for num in range(5):
                for i in range(num):
                    _create_person(distinct_ids=[f"person_{num}_{i}"], team_id=self.team.pk)
                    _create_event(
                        team=self.team,
                        event="sign up",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T12:00:00Z",
                    )
                    _create_event(
                        team=self.team,
                        event="play movie",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T13:00:00Z",
                    )
                    _create_event(
                        team=self.team,
                        event="buy",
                        distinct_id=f"person_{num}_{i}",
                        properties={"key": "val", "some_breakdown_val": num},
                        timestamp="2020-01-01T15:00:00Z",
                    )

            # no breakdown value for this guy
            p_null = _create_person(distinct_ids=[f"person_null"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id=f"person_null",
                properties={"key": "val"},
                timestamp="2020-01-01T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id=f"person_null",
                properties={"key": "val"},
                timestamp="2020-01-01T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="buy",
                distinct_id=f"person_null",
                properties={"key": "val"},
                timestamp="2020-01-01T15:00:00Z",
            )

            result = funnel.run()

            breakdown_vals = sorted([res[0]["breakdown"] for res in result])
            self.assertEqual(["", "1", "2", "3", "4"], breakdown_vals)
            # included 1 and '' because the limit was 6.

            for i in range(1, 5):
                self.assertEqual(len(self._get_people_at_step(filter, 3, str(i))), i)

            self.assertEqual([p_null.uuid], self._get_people_at_step(filter, 1, ""))
            self.assertEqual([p_null.uuid], self._get_people_at_step(filter, 3, ""))

        def test_funnel_step_breakdown_event_single_person_multiple_breakdowns(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "$browser",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Chrome"},
                timestamp="2020-01-01T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Mac"},
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val", "$browser": 0},  # mixed property type!
                timestamp="2020-01-02T15:00:00Z",
            )

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(
                result[0],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "0",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "0"), [person1.uuid])

            self.assertEqual(
                result[1],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Chrome",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Chrome"), [person1.uuid])

            self.assertEqual(
                result[2],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Mac",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Mac"), [person1.uuid])

            self.assertEqual(
                result[3],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari"), [person1.uuid])

        def test_funnel_step_breakdown_event_single_person_events_with_multiple_properties(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "$browser",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Chrome"},
                timestamp="2020-01-01T12:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T12:30:00Z",
            )
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T13:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person1",
                properties={"key": "val", "$browser": "Safari"},
                timestamp="2020-01-02T14:00:00Z",
            )

            result = funnel.run()
            self.assertEqual(
                result[0],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Chrome",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "order": 1,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Chrome",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Chrome"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Chrome"), [])

            self.assertEqual(
                result[1],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "order": 0,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "order": 1,
                        "people": [person1.uuid] if Funnel == ClickhouseFunnel else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 3600,
                        "median_conversion_time": 3600,
                        "breakdown": "Safari",
                    },
                ],
            )
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Safari"), [person1.uuid])

        def test_funnel_cohort_breakdown(self):
            # This caused some issues with SQL parsing
            person = _create_person(distinct_ids=[f"person1"], team_id=self.team.pk, properties={"key": "value"})
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id=f"person1",
                properties={},
                timestamp="2020-01-02T12:00:00Z",
            )
            cohort = Cohort.objects.create(
                team=self.team, name="test_cohort", groups=[{"properties": {"key": "value"}}]
            )
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "cohort",
                "breakdown": [cohort.pk],
            }
            filter = Filter(data=filters)
            funnel = ClickhouseFunnel(filter, self.team)

            result = funnel.run()
            self.assertEqual(len(result[0]), 3)
            self.assertEqual(result[0][0]["breakdown"], "test_cohort")
            self.assertCountEqual(self._get_people_at_step(filter, 1, cohort.pk), [person.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, cohort.pk), [])

            # non array
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "cohort",
                "breakdown": cohort.pk,
            }
            filter = Filter(data=filters)
            funnel = ClickhouseFunnel(filter, self.team)

            result = funnel.run()
            self.assertEqual(len(result[0]), 3)
            self.assertEqual(result[0][0]["breakdown"], "test_cohort")
            self.assertCountEqual(self._get_people_at_step(filter, 1, cohort.pk), [person.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, cohort.pk), [])

    return TestFunnelBreakdown
