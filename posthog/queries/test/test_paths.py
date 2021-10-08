from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.constants import FILTER_TEST_ACCOUNTS
from posthog.models import Element, Event, Person
from posthog.models.filters.path_filter import PathFilter
from posthog.queries.paths import Paths
from posthog.test.base import APIBaseTest


def paths_test_factory(paths, event_factory, person_factory):
    class TestPaths(APIBaseTest):
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
                person_factory(
                    team_id=self.team.pk, distinct_ids=["person_1"], properties={"email": "test@posthog.com"}
                )
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
                filter = PathFilter(data={"dummy": "dummy"})
                response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

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
                response = self.client.get(
                    "/api/insight/path/?insight=PATHS&date_from=" + date_from.strftime("%Y-%m-%d")
                ).json()
                self.assertEqual(len(response["result"]), 4)

                date_to = now()
                response = self.client.get(
                    "/api/insight/path/?insight=PATHS&date_to=" + date_to.strftime("%Y-%m-%d")
                ).json()
                self.assertEqual(len(response["result"]), 4)

                date_from = now() + relativedelta(days=7)
                response = self.client.get(
                    "/api/insight/path/?insight=PATHS&date_from=" + date_from.strftime("%Y-%m-%d")
                ).json()
                self.assertEqual(len(response["result"]), 0)

                date_to = now() - relativedelta(days=7)
                response = self.client.get(
                    "/api/insight/path/?insight=PATHS&date_to=" + date_to.strftime("%Y-%m-%d")
                ).json()
                self.assertEqual(len(response["result"]), 0)

                date_from = now() - relativedelta(days=7)
                date_to = now() + relativedelta(days=7)

                date_params = {"date_from": date_from.strftime("%Y-%m-%d"), "date_to": date_to.strftime("%Y-%m-%d")}

                filter = PathFilter(data={**date_params})
                response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
                self.assertEqual(len(response), 4)

                # Test account filter
                filter = PathFilter(data={**date_params, FILTER_TEST_ACCOUNTS: True}, team=self.team)
                response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
                self.assertEqual(len(response), 3)

                date_from = now() + relativedelta(days=7)
                date_to = now() - relativedelta(days=7)
                date_params = {"date_from": date_from.strftime("%Y-%m-%d"), "date_to": date_to.strftime("%Y-%m-%d")}
                filter = PathFilter(data={**date_params}, team=self.team)
                response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
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

            filter = PathFilter(data={"path_type": "custom_event"})
            response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

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

            filter = PathFilter(data={"path_type": "$screen"})
            response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter)
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

            filter = PathFilter(data={"properties": [{"key": "$browser", "value": "Chrome", "type": "event"}]})

            response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

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

            response = self.client.get("/api/insight/path/?type=%24pageview&start=%2Fpricing").json()

            filter = PathFilter(data={"path_type": "$pageview", "start_point": "/pricing"})
            response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter,)

            self.assertEqual(len(response), 5)

            self.assertTrue(response[0].items() >= {"source": "1_/pricing", "target": "2_/about", "value": 2}.items())
            self.assertTrue(response[1].items() >= {"source": "1_/pricing", "target": "2_/", "value": 1}.items())
            self.assertTrue(response[2].items() >= {"source": "2_/", "target": "3_/about", "value": 1}.items())
            self.assertTrue(response[3].items() >= {"source": "2_/about", "target": "3_/pricing", "value": 1}.items())
            self.assertTrue(response[4].items() >= {"source": "3_/pricing", "target": "4_/help", "value": 1}.items())

            filter = PathFilter(data={"path_type": "$pageview", "start_point": "/"})
            response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter,)

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
            filter = PathFilter(data={"date_from": "2020-04-13"})
            response = paths(team=self.team, filter=filter).run(team=self.team, filter=filter)

            self.assertEqual(response[0]["source"], "1_/")
            self.assertEqual(response[0]["target"], "2_/about")
            self.assertEqual(response[0]["value"], 2)

    return TestPaths


class DjangoPathsTest(paths_test_factory(Paths, Event.objects.create, Person.objects.create)):  # type: ignore
    pass
