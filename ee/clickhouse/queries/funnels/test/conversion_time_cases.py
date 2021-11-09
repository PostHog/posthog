from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters import Filter
from posthog.test.base import APIBaseTest


def funnel_conversion_time_test_factory(Funnel, FunnelPerson, _create_event, _create_person):
    class TestFunnelConversionTime(APIBaseTest):
        def _get_people_at_step(self, filter, funnel_step):
            person_filter = filter.with_data({"funnel_step": funnel_step})
            result = FunnelPerson(person_filter, self.team)._exec_query()
            return [row[0] for row in result]

        def test_funnel_with_multiple_incomplete_tries(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "$pageview", "type": "events", "order": 1},
                    {"id": "something else", "type": "events", "order": 2},
                ],
                "funnel_window_days": 1,
                "date_from": "2021-05-01 00:00:00",
                "date_to": "2021-05-14 00:00:00",
                "insight": INSIGHT_FUNNELS,
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id="person1", timestamp="2021-05-01 01:00:00"
            )
            _create_event(team=self.team, event="$pageview", distinct_id="person1", timestamp="2021-05-01 02:00:00")
            _create_event(
                team=self.team, event="something else", distinct_id="person1", timestamp="2021-05-01 03:00:00"
            )
            # person1 completed funnel on 2021-05-01

            _create_event(
                team=self.team, event="user signed up", distinct_id="person1", timestamp="2021-05-03 04:00:00"
            )
            _create_event(team=self.team, event="$pageview", distinct_id="person1", timestamp="2021-05-03 06:00:00")
            # person1 completed part of funnel on 2021-05-03 and took 2 hours to convert

            _create_event(
                team=self.team, event="user signed up", distinct_id="person1", timestamp="2021-05-04 07:00:00"
            )
            _create_event(team=self.team, event="$pageview", distinct_id="person1", timestamp="2021-05-04 10:00:00")
            # person1 completed part of funnel on 2021-05-04 and took 3 hours to convert

            result = funnel.run()

            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[1]["name"], "$pageview")
            self.assertEqual(result[2]["name"], "something else")
            self.assertEqual(result[0]["count"], 1)
            self.assertEqual(
                result[1]["average_conversion_time"], 3600
            )  # one hour to convert, disregard the incomplete tries
            self.assertEqual(result[1]["median_conversion_time"], 3600)

            # check ordering of people in every step
            self.assertCountEqual(
                self._get_people_at_step(filter, 1), [person1.uuid,],
            )

        def test_funnel_step_conversion_times(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
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

            person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
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

            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person3",
                properties={"key": "val"},
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team,
                event="play movie",
                distinct_id="person3",
                properties={"key": "val"},
                timestamp="2020-01-02T16:00:00Z",
            )
            _create_event(
                team=self.team,
                event="buy",
                distinct_id="person3",
                properties={"key": "val"},
                timestamp="2020-01-02T17:00:00Z",
            )

            result = funnel.run()

            self.assertEqual(result[0]["average_conversion_time"], None)
            self.assertEqual(result[1]["average_conversion_time"], 6000)
            self.assertEqual(result[2]["average_conversion_time"], 5400)

            self.assertEqual(result[0]["median_conversion_time"], None)
            self.assertEqual(result[1]["median_conversion_time"], 7200)
            self.assertEqual(result[2]["median_conversion_time"], 5400)

        def test_funnel_times_with_different_conversion_windows(self):
            filters = {
                "events": [
                    {"id": "user signed up", "type": "events", "order": 0},
                    {"id": "pageview", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "funnel_window_interval": 14,
                "funnel_window_interval_unit": "day",
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            person1_stopped_after_two_signups = _create_person(
                distinct_ids=["stopped_after_signup1"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup1",
                timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team, event="pageview", distinct_id="stopped_after_signup1", timestamp="2020-01-02T14:05:00Z"
            )

            person2_stopped_after_signup = _create_person(distinct_ids=["stopped_after_signup2"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup2",
                timestamp="2020-01-02T14:03:00Z",
            )

            person3_stopped_after_two_signups = _create_person(
                distinct_ids=["stopped_after_signup3"], team_id=self.team.pk
            )
            _create_event(
                team=self.team,
                event="user signed up",
                distinct_id="stopped_after_signup3",
                timestamp="2020-01-02T12:00:00Z",
            )
            _create_event(
                team=self.team, event="pageview", distinct_id="stopped_after_signup3", timestamp="2020-01-02T12:15:00Z"
            )

            result = funnel.run()
            self.assertEqual(result[0]["name"], "user signed up")
            self.assertEqual(result[0]["count"], 3)
            self.assertEqual(result[1]["count"], 2)
            self.assertEqual(result[1]["average_conversion_time"], 600)

            self.assertCountEqual(
                self._get_people_at_step(filter, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                    person3_stopped_after_two_signups.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_people_at_step(filter, 2),
                [person1_stopped_after_two_signups.uuid, person3_stopped_after_two_signups.uuid],
            )

            filter = filter.with_data({"funnel_window_interval": 5, "funnel_window_interval_unit": "minute"})

            funnel = Funnel(filter, self.team)
            result4 = funnel.run()

            self.assertNotEqual(result, result4)
            self.assertEqual(result4[0]["name"], "user signed up")
            self.assertEqual(result4[0]["count"], 3)
            self.assertEqual(result4[1]["count"], 1)
            self.assertEqual(result4[1]["average_conversion_time"], 300)

            self.assertCountEqual(
                self._get_people_at_step(filter, 1),
                [
                    person1_stopped_after_two_signups.uuid,
                    person2_stopped_after_signup.uuid,
                    person3_stopped_after_two_signups.uuid,
                ],
            )

            self.assertCountEqual(
                self._get_people_at_step(filter, 2), [person1_stopped_after_two_signups.uuid],
            )

    return TestFunnelConversionTime
