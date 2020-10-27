from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models import Element, Event, Filter, Person
from posthog.queries.paths import Paths
from posthog.utils import request_to_date_query


def paths_test_factory(paths, event_factory, person_factory):
    class TestPaths(BaseTest):
        TESTS_API = True

        def test_current_url_paths_and_logic(self):

            with freeze_time("2012-01-01T03:21:34.000Z"):
                person_factory(team_id=self.team.pk, distinct_ids=["fake"])
                event_factory(
                    properties={"$current_url": "/"}, distinct_id="fake", event="$pageview", team=self.team,
                )
                event_factory(
                    properties={"$current_url": "/about"}, distinct_id="fake", event="$pageview", team=self.team,
                )

            with freeze_time("2012-01-14T03:21:34.000Z"):
                person_factory(team_id=self.team.pk, distinct_ids=["person_1"])
                event_factory(
                    properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
                )
            with freeze_time("2012-01-14T03:28:34.000Z"):
                event_factory(
                    properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
                )

            with freeze_time("2012-01-14T03:21:34.000Z"):
                person_factory(team_id=self.team.pk, distinct_ids=["person_2a", "person_2b"])
                event_factory(
                    properties={"$current_url": "/"}, distinct_id="person_2a", event="$pageview", team=self.team,
                )
            with freeze_time("2012-01-14T03:28:34.000Z"):
                event_factory(
                    properties={"$current_url": "/pricing"}, distinct_id="person_2b", event="$pageview", team=self.team,
                )
            with freeze_time("2012-01-14T03:29:34.000Z"):
                event_factory(
                    properties={"$current_url": "/about"}, distinct_id="person_2a", event="$pageview", team=self.team,
                )

            with freeze_time("2012-01-14T03:21:34.000Z"):
                person_factory(team_id=self.team.pk, distinct_ids=["person_3"])
                event_factory(
                    properties={"$current_url": "/pricing"}, distinct_id="person_3", event="$pageview", team=self.team,
                )
            with freeze_time("2012-01-14T03:28:34.000Z"):
                event_factory(
                    properties={"$current_url": "/"}, distinct_id="person_3", event="$pageview", team=self.team,
                )

            with freeze_time("2012-01-14T03:21:34.000Z"):
                person_factory(team_id=self.team.pk, distinct_ids=["person_4"])
                event_factory(
                    properties={"$current_url": "/"}, distinct_id="person_4", event="$pageview", team=self.team,
                )
            with freeze_time("2012-01-14T03:28:34.000Z"):
                event_factory(
                    properties={"$current_url": "/pricing"}, distinct_id="person_4", event="$pageview", team=self.team,
                )

            with freeze_time("2012-01-15T03:21:34.000Z"):
                filter = Filter(data={"dummy": "dummy"})
                response = paths().run(team=self.team, filter=filter)

            self.assertEqual(response[0]["source"], "1_/", response)
            self.assertEqual(response[0]["target"], "2_/pricing")
            self.assertEqual(response[0]["value"], 2)

            self.assertEqual(response[1]["source"], "1_/")
            self.assertEqual(response[1]["target"], "2_/about")
            self.assertEqual(response[1]["value"], 1)

            self.assertEqual(response[2]["source"], "1_/pricing")
            self.assertEqual(response[2]["target"], "2_/")
            self.assertEqual(response[2]["value"], 1)

            self.assertEqual(response[3]["source"], "2_/pricing", response[3])
            self.assertEqual(response[3]["target"], "3_/about")
            self.assertEqual(response[3]["value"], 1)

            with freeze_time("2012-01-15T03:21:34.000Z"):
                date_from = now() - relativedelta(days=7)
                response = self.client.get("/api/paths/?date_from=" + date_from.strftime("%Y-%m-%d")).json()
                self.assertEqual(len(response), 4)

                date_to = now()
                response = self.client.get("/api/paths/?date_to=" + date_to.strftime("%Y-%m-%d")).json()
                self.assertEqual(len(response), 4)

                date_from = now() + relativedelta(days=7)
                response = self.client.get("/api/paths/?date_from=" + date_from.strftime("%Y-%m-%d")).json()
                self.assertEqual(len(response), 0)

                date_to = now() - relativedelta(days=7)
                response = self.client.get("/api/paths/?date_to=" + date_to.strftime("%Y-%m-%d")).json()
                self.assertEqual(len(response), 0)

                date_from = now() - relativedelta(days=7)
                date_to = now() + relativedelta(days=7)

                date_params = {"date_from": date_from.strftime("%Y-%m-%d"), "date_to": date_to.strftime("%Y-%m-%d")}

                filter = Filter(data={**date_params})
                response = paths().run(team=self.team, filter=filter)
                self.assertEqual(len(response), 4)

                date_from = now() + relativedelta(days=7)
                date_to = now() - relativedelta(days=7)
                date_params = {"date_from": date_from.strftime("%Y-%m-%d"), "date_to": date_to.strftime("%Y-%m-%d")}
                filter = Filter(data={**date_params})
                response = paths().run(team=self.team, filter=filter)
                self.assertEqual(len(response), 0)

        def test_custom_event_paths(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"])
            event_factory(distinct_id="person_1", event="custom_event_1", team=self.team)
            event_factory(distinct_id="person_1", event="custom_event_3", team=self.team)
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
            )  # should be ignored

            person_factory(team_id=self.team.pk, distinct_ids=["person_2"])
            event_factory(distinct_id="person_2", event="custom_event_1", team=self.team)
            event_factory(distinct_id="person_2", event="custom_event_2", team=self.team)
            event_factory(distinct_id="person_2", event="custom_event_3", team=self.team)

            person_factory(team_id=self.team.pk, distinct_ids=["person_3"])
            event_factory(distinct_id="person_3", event="custom_event_2", team=self.team)
            event_factory(distinct_id="person_3", event="custom_event_1", team=self.team)

            person_factory(team_id=self.team.pk, distinct_ids=["person_4"])
            event_factory(distinct_id="person_4", event="custom_event_1", team=self.team)
            event_factory(distinct_id="person_4", event="custom_event_2", team=self.team)

            response = paths().run(team=self.team, filter=Filter(data={"path_type": "custom_event"}))

            self.assertEqual(response[0]["source"], "1_custom_event_1", response)
            self.assertEqual(response[0]["target"], "2_custom_event_2")
            self.assertEqual(response[0]["value"], 2)

            self.assertEqual(response[1]["source"], "1_custom_event_1")
            self.assertEqual(response[1]["target"], "2_custom_event_3")
            self.assertEqual(response[1]["value"], 1)

            self.assertEqual(response[2]["source"], "1_custom_event_2")
            self.assertEqual(response[2]["target"], "2_custom_event_1")
            self.assertEqual(response[2]["value"], 1)

            self.assertEqual(response[3]["source"], "2_custom_event_2", response[3])
            self.assertEqual(response[3]["target"], "3_custom_event_3")
            self.assertEqual(response[3]["value"], 1)

        def test_screen_paths(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"])
            event_factory(
                properties={"$screen_name": "/"}, distinct_id="person_1", event="$screen", team=self.team,
            )
            event_factory(
                properties={"$screen_name": "/about"}, distinct_id="person_1", event="$screen", team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_2a", "person_2b"])
            event_factory(
                properties={"$screen_name": "/"}, distinct_id="person_2b", event="$screen", team=self.team,
            )
            event_factory(
                properties={"$screen_name": "/pricing"}, distinct_id="person_2a", event="$screen", team=self.team,
            )
            event_factory(
                properties={"$screen_name": "/about"}, distinct_id="person_2b", event="$screen", team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_3"])
            event_factory(
                properties={"$screen_name": "/pricing"}, distinct_id="person_3", event="$screen", team=self.team,
            )
            event_factory(
                properties={"$screen_name": "/"}, distinct_id="person_3", event="$screen", team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_4"])
            event_factory(
                properties={"$screen_name": "/"}, distinct_id="person_4", event="$screen", team=self.team,
            )
            event_factory(
                properties={"$screen_name": "/pricing"}, distinct_id="person_4", event="$screen", team=self.team,
            )

            response = paths().run(team=self.team, filter=Filter(data={"path_type": "$screen"}))
            self.assertEqual(response[0]["source"], "1_/", response)
            self.assertEqual(response[0]["target"], "2_/pricing")
            self.assertEqual(response[0]["value"], 2)

            self.assertEqual(response[1]["source"], "1_/")
            self.assertEqual(response[1]["target"], "2_/about")
            self.assertEqual(response[1]["value"], 1)

            self.assertEqual(response[2]["source"], "1_/pricing")
            self.assertEqual(response[2]["target"], "2_/")
            self.assertEqual(response[2]["value"], 1)

            self.assertEqual(response[3]["source"], "2_/pricing", response[3])
            self.assertEqual(response[3]["target"], "3_/about")
            self.assertEqual(response[3]["value"], 1)

        def test_autocapture_paths(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"])

            event_factory(
                event="$autocapture",
                team=self.team,
                distinct_id="person_1",
                elements=[
                    Element(tag_name="a", text="hello", href="/a-url", nth_child=1, nth_of_type=0),
                    Element(tag_name="button", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested",),
                ],
            )

            event_factory(
                event="$autocapture",
                team=self.team,
                distinct_id="person_1",
                elements=[
                    Element(tag_name="a", text="goodbye", nth_child=2, nth_of_type=0, attr_id="someId",),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(href="/a-url-2", nth_child=0, nth_of_type=0),
                ],
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_2"])
            event_factory(
                event="$autocapture",
                team=self.team,
                distinct_id="person_2",
                elements=[
                    Element(tag_name="a", text="hello1", href="/a-url", nth_child=1, nth_of_type=0,),
                    Element(tag_name="button", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    Element(tag_name="div", nth_child=0, nth_of_type=0, attr_id="nested",),
                ],
            )

            event_factory(
                event="$autocapture",
                team=self.team,
                distinct_id="person_2",
                elements=[
                    Element(tag_name="a", text="goodbye1", nth_child=2, nth_of_type=0, attr_id="someId",),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(href="/a-url-2", nth_child=0, nth_of_type=0),
                ],
            )

            event_factory(
                event="$autocapture",
                team=self.team,
                distinct_id="person_2",
                elements=[
                    Element(tag_name="a", text="goodbye1", nth_child=2, nth_of_type=0, attr_id="someId",),
                    Element(tag_name="div", nth_child=0, nth_of_type=0),
                    # make sure elements don't get double counted if they're part of the same event
                    Element(href="/a-url-2", nth_child=0, nth_of_type=0),
                ],
            )

            response = paths().run(team=self.team, filter=Filter(data={"path_type": "$autocapture"}))

            self.assertEqual(response[0]["source"], "1_<a> hello")
            self.assertEqual(response[0]["target"], "2_<a> goodbye")
            self.assertEqual(response[0]["value"], 1)

            self.assertEqual(response[1]["source"], "1_<a> hello1")
            self.assertEqual(response[1]["target"], "2_<a> goodbye1")
            self.assertEqual(response[1]["value"], 1)

            self.assertEqual(response[2]["source"], "2_<a> goodbye1")
            self.assertEqual(response[2]["target"], "3_<a> goodbye1")
            self.assertEqual(response[2]["value"], 1)

            elements = self.client.get("/api/paths/elements/").json()
            self.assertEqual(elements[0]["name"], "<a> goodbye1")  # first since captured twice
            self.assertEqual(elements[1]["name"], "<a> goodbye")
            self.assertEqual(elements[2]["name"], "<a> hello")
            self.assertEqual(elements[3]["name"], "<a> hello1")
            self.assertEqual(len(elements), 4)

        def test_paths_properties_filter(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"])
            event_factory(
                properties={"$current_url": "/", "$browser": "Chrome"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            )
            event_factory(
                properties={"$current_url": "/about", "$browser": "Chrome"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_2"])
            event_factory(
                properties={"$current_url": "/", "$browser": "Chrome"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            )
            event_factory(
                properties={"$current_url": "/pricing", "$browser": "Chrome"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            )
            event_factory(
                properties={"$current_url": "/about", "$browser": "Chrome"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_3"])
            event_factory(
                properties={"$current_url": "/pricing"}, distinct_id="person_3", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_3", event="$pageview", team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_4"])
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_4", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/pricing"}, distinct_id="person_4", event="$pageview", team=self.team,
            )

            filter = Filter(data={"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]})

            response = paths().run(team=self.team, filter=filter)

            self.assertEqual(response[0]["source"], "1_/")
            self.assertEqual(response[0]["target"], "2_/about")
            self.assertEqual(response[0]["value"], 1)

            self.assertEqual(response[1]["source"], "1_/")
            self.assertEqual(response[1]["target"], "2_/pricing")
            self.assertEqual(response[1]["value"], 1)

            self.assertEqual(response[2]["source"], "2_/pricing")
            self.assertEqual(response[2]["target"], "3_/about")
            self.assertEqual(response[2]["value"], 1)

        def test_paths_start(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"])
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_2"])
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_2", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/pricing"}, distinct_id="person_2", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/about"}, distinct_id="person_2", event="$pageview", team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_3"])
            event_factory(
                properties={"$current_url": "/pricing"}, distinct_id="person_3", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_3", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/about"}, distinct_id="person_3", event="$pageview", team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_4"])
            event_factory(
                properties={"$current_url": "/"}, distinct_id="person_4", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/pricing"}, distinct_id="person_4", event="$pageview", team=self.team,
            )

            person_factory(team_id=self.team.pk, distinct_ids=["person_5a", "person_5b"])
            event_factory(
                properties={"$current_url": "/pricing"}, distinct_id="person_5a", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/about"}, distinct_id="person_5b", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/pricing"}, distinct_id="person_5a", event="$pageview", team=self.team,
            )
            event_factory(
                properties={"$current_url": "/help"}, distinct_id="person_5b", event="$pageview", team=self.team,
            )

            response = self.client.get("/api/paths/?type=%24pageview&start=%2Fpricing").json()

            response = paths().run(
                team=self.team, filter=Filter(data={"path_type": "$pageview", "start_point": "/pricing"}),
            )

            self.assertEqual(len(response), 5)

            self.assertTrue(response[0].items() >= {"source": "1_/pricing", "target": "2_/about", "value": 2}.items())
            self.assertTrue(response[1].items() >= {"source": "1_/pricing", "target": "2_/", "value": 1}.items())
            self.assertTrue(response[2].items() >= {"source": "2_/", "target": "3_/about", "value": 1}.items())
            self.assertTrue(response[3].items() >= {"source": "2_/about", "target": "3_/pricing", "value": 1}.items())
            self.assertTrue(response[4].items() >= {"source": "3_/pricing", "target": "4_/help", "value": 1}.items())

            response = paths().run(team=self.team, filter=Filter(data={"path_type": "$pageview", "start_point": "/"}),)

            self.assertEqual(len(response), 3)

            self.assertTrue(response[0].items() >= {"source": "1_/", "target": "2_/about", "value": 2}.items())
            self.assertTrue(response[1].items() >= {"source": "1_/", "target": "2_/pricing", "value": 2}.items())
            self.assertTrue(response[2].items() >= {"source": "2_/pricing", "target": "3_/about", "value": 1}.items())

        def test_paths_in_window(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"])

            with freeze_time("2020-04-14T03:25:34.000Z"):
                event_factory(
                    properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
                )
            with freeze_time("2020-04-14T03:30:34.000Z"):
                event_factory(
                    properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
                )

            with freeze_time("2020-04-15T03:25:34.000Z"):
                event_factory(
                    properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
                )
            with freeze_time("2020-04-15T03:30:34.000Z"):
                event_factory(
                    properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
                )

            response = paths().run(team=self.team, filter=Filter(data={"date_from": "2020-04-13"}))

            self.assertEqual(response[0]["source"], "1_/")
            self.assertEqual(response[0]["target"], "2_/about")
            self.assertEqual(response[0]["value"], 2)

    return TestPaths


class DjangoPathsTest(paths_test_factory(Paths, Event.objects.create, Person.objects.create)):  # type: ignore
    pass
