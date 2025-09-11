import dataclasses

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
)

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.schema import CachedPathsQueryResponse

from posthog.hogql_queries.insights.paths_query_runner import PathsQueryRunner
from posthog.models import Team


# This test file uses a batched method of event creation
# We collect all events per test into an array and batch create the events to reduce creation time
@dataclasses.dataclass
class MockEvent:
    event: str
    distinct_id: str
    team: Team
    timestamp: str
    properties: dict


class TestPaths(ClickhouseTestMixin, APIBaseTest):
    @also_test_with_materialized_columns(["$current_url", "$screen_name"], person_properties=["email"])
    def test_current_url_paths_and_logic(self):
        events = []
        _create_person(team_id=self.team.pk, distinct_ids=["fake"])
        events.extend(
            [
                _create_event(
                    properties={"$current_url": "/"},
                    distinct_id="fake",
                    event="$pageview",
                    team=self.team,
                    timestamp="2012-01-01 03:21:34",
                ),
                _create_event(
                    properties={"$current_url": "/about"},
                    distinct_id="fake",
                    event="$pageview",
                    team=self.team,
                    timestamp="2012-01-01 03:21:34",
                ),
            ]
        )

        _create_person(
            team_id=self.team.pk,
            distinct_ids=["person_1"],
            properties={"email": "test@posthog.com"},
        )
        events.append(
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:21:34",
            )
        )
        events.append(
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:28:34",
            )
        )

        _create_person(team_id=self.team.pk, distinct_ids=["person_2a", "person_2b"])
        events.append(
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_2a",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:21:34",
            )
        )
        events.append(
            _create_event(
                properties={"$current_url": "/pricing"},
                distinct_id="person_2b",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:28:34",
            )
        )
        events.append(
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_2a",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:29:34",
            )
        )

        _create_person(team_id=self.team.pk, distinct_ids=["person_3"])
        events.append(
            _create_event(
                properties={"$current_url": "/pricing"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:21:34",
            )
        )

        events.append(
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:28:34",
            )
        )

        _create_person(team_id=self.team.pk, distinct_ids=["person_4"])
        events.append(
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_4",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:21:34",
            )
        )
        events.append(
            _create_event(
                properties={"$current_url": "/pricing"},
                distinct_id="person_4",
                event="$pageview",
                team=self.team,
                timestamp="2012-01-14 03:28:34",
            )
        )

        with freeze_time("2012-01-15T03:21:34.000Z"):
            result = PathsQueryRunner(
                query={
                    "kind": "PathsQuery",
                    "pathsFilter": {},  # Not actually possible in frontend?!?
                },
                team=self.team,
            ).run()
            assert isinstance(result, CachedPathsQueryResponse)
            response = result.results

        self.assertEqual(response[0].source, "1_/", response)
        self.assertEqual(response[0].target, "2_/pricing")
        self.assertEqual(response[0].value, 2)

        self.assertEqual(response[1].source, "1_/")
        self.assertEqual(response[1].target, "2_/about")
        self.assertEqual(response[1].value, 1)

        self.assertEqual(response[2].source, "1_/pricing")
        self.assertEqual(response[2].target, "2_/")
        self.assertEqual(response[2].value, 1)

        self.assertEqual(response[3].source, "2_/pricing", response[3])
        self.assertEqual(response[3].target, "3_/about")
        self.assertEqual(response[3].value, 1)

        with freeze_time("2012-01-15T03:21:34.000Z"):
            date_from = now() - relativedelta(days=7)
            result = PathsQueryRunner(
                query={
                    "kind": "PathsQuery",
                    "dateRange": {
                        "date_from": date_from.strftime("%Y-%m-%d"),
                    },
                    "pathsFilter": {},
                },
                team=self.team,
            ).run()

            assert hasattr(result, "results")
            self.assertEqual(len(result.results), 4)

            date_to = now()
            result = PathsQueryRunner(
                query={
                    "kind": "PathsQuery",
                    "dateRange": {
                        "date_to": date_to.strftime("%Y-%m-%d"),
                    },
                    "pathsFilter": {},
                },
                team=self.team,
            ).run()

            assert isinstance(result, CachedPathsQueryResponse)
            self.assertEqual(len(result.results), 4)

            date_from = now() + relativedelta(days=7)
            result = PathsQueryRunner(
                query={
                    "kind": "PathsQuery",
                    "dateRange": {
                        "date_from": date_from.strftime("%Y-%m-%d"),
                    },
                    "pathsFilter": {},
                },
                team=self.team,
            ).run()

            assert isinstance(result, CachedPathsQueryResponse)
            self.assertEqual(len(result.results), 0)

            date_to = now() - relativedelta(days=7)
            result = PathsQueryRunner(
                query={
                    "kind": "PathsQuery",
                    "dateRange": {
                        "date_to": date_to.strftime("%Y-%m-%d"),
                    },
                    "pathsFilter": {},
                },
                team=self.team,
            ).run()

            assert isinstance(result, CachedPathsQueryResponse)
            self.assertEqual(len(result.results), 0)

            date_from = now() - relativedelta(days=7)
            date_to = now() + relativedelta(days=7)

            result = PathsQueryRunner(
                query={
                    "kind": "PathsQuery",
                    "dateRange": {
                        "date_from": date_from.strftime("%Y-%m-%d"),
                        "date_to": date_to.strftime("%Y-%m-%d"),
                    },
                    "pathsFilter": {},
                },
                team=self.team,
            ).run()
            assert isinstance(result, CachedPathsQueryResponse)
            self.assertEqual(len(result.results), 4)

            # Test account filter
            result = PathsQueryRunner(
                query={
                    "kind": "PathsQuery",
                    "dateRange": {
                        "date_from": date_from.strftime("%Y-%m-%d"),
                        "date_to": date_to.strftime("%Y-%m-%d"),
                    },
                    "filterTestAccounts": True,
                    "pathsFilter": {},
                },
                team=self.team,
            ).run()

            assert isinstance(result, CachedPathsQueryResponse)
            self.assertEqual(len(result.results), 3)

            date_from = now() + relativedelta(days=7)
            date_to = now() - relativedelta(days=7)
            result = PathsQueryRunner(
                query={
                    "kind": "PathsQuery",
                    "dateRange": {
                        "date_from": date_from.strftime("%Y-%m-%d"),
                        "date_to": date_to.strftime("%Y-%m-%d"),
                    },
                    "pathsFilter": {},
                },
                team=self.team,
            ).run()

            assert isinstance(result, CachedPathsQueryResponse)
            self.assertEqual(len(result.results), 0)

    def test_custom_event_paths(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person_1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_4"])

        (
            _create_event(
                distinct_id="person_1",
                event="custom_event_1",
                team=self.team,
                properties={},
            ),
        )
        (
            _create_event(
                distinct_id="person_1",
                event="custom_event_3",
                team=self.team,
                properties={},
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            ),
        )  # should be ignored,
        (
            _create_event(
                distinct_id="person_2",
                event="custom_event_1",
                team=self.team,
                properties={},
            ),
        )
        (
            _create_event(
                distinct_id="person_2",
                event="custom_event_2",
                team=self.team,
                properties={},
            ),
        )
        (
            _create_event(
                distinct_id="person_2",
                event="custom_event_3",
                team=self.team,
                properties={},
            ),
        )
        (
            _create_event(
                distinct_id="person_3",
                event="custom_event_2",
                team=self.team,
                properties={},
            ),
        )
        (
            _create_event(
                distinct_id="person_3",
                event="custom_event_1",
                team=self.team,
                properties={},
            ),
        )
        (
            _create_event(
                distinct_id="person_4",
                event="custom_event_1",
                team=self.team,
                properties={},
            ),
        )
        (
            _create_event(
                distinct_id="person_4",
                event="custom_event_2",
                team=self.team,
                properties={},
            ),
        )

        r = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "pathsFilter": {
                    "includeEventTypes": ["custom_event"],
                },
            },
            team=self.team,
        ).run()
        assert isinstance(r, CachedPathsQueryResponse)
        response = r.results

        self.assertEqual(response[0].source, "1_custom_event_1", response)
        self.assertEqual(response[0].target, "2_custom_event_2")
        self.assertEqual(response[0].value, 2)

        self.assertEqual(response[1].source, "1_custom_event_1")
        self.assertEqual(response[1].target, "2_custom_event_3")
        self.assertEqual(response[1].value, 1)

        self.assertEqual(response[2].source, "1_custom_event_2")
        self.assertEqual(response[2].target, "2_custom_event_1")
        self.assertEqual(response[2].value, 1)

        self.assertEqual(response[3].source, "2_custom_event_2", response[3])
        self.assertEqual(response[3].target, "3_custom_event_3")
        self.assertEqual(response[3].value, 1)

    def test_custom_hogql_paths(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person_1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_4"])

        (
            _create_event(
                distinct_id="person_1",
                event="custom_event_1",
                team=self.team,
                properties={"a": "!"},
            ),
        )
        (
            _create_event(
                distinct_id="person_1",
                event="custom_event_3",
                team=self.team,
                properties={"a": "!"},
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            ),
        )  # should be ignored,
        (
            _create_event(
                distinct_id="person_2",
                event="custom_event_1",
                team=self.team,
                properties={"a": "!"},
            ),
        )
        (
            _create_event(
                distinct_id="person_2",
                event="custom_event_2",
                team=self.team,
                properties={"a": "!"},
            ),
        )
        (
            _create_event(
                distinct_id="person_2",
                event="custom_event_3",
                team=self.team,
                properties={"a": "!"},
            ),
        )
        (
            _create_event(
                distinct_id="person_3",
                event="custom_event_2",
                team=self.team,
                properties={"a": "!"},
            ),
        )
        (
            _create_event(
                distinct_id="person_3",
                event="custom_event_1",
                team=self.team,
                properties={"a": "!"},
            ),
        )
        (
            _create_event(
                distinct_id="person_4",
                event="custom_event_1",
                team=self.team,
                properties={"a": "!"},
            ),
        )
        (
            _create_event(
                distinct_id="person_4",
                event="custom_event_2",
                team=self.team,
                properties={"a": "!"},
            ),
        )

        r = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "pathsFilter": {
                    "includeEventTypes": ["hogql"],
                    "pathsHogQLExpression": "event || properties.a",
                },
            },
            team=self.team,
        ).run()
        assert isinstance(r, CachedPathsQueryResponse)
        response = r.results

        self.assertEqual(response[0].source, "1_custom_event_1!", response)
        self.assertEqual(response[0].target, "2_custom_event_2!")
        self.assertEqual(response[0].value, 2)

        self.assertEqual(response[1].source, "1_custom_event_1!")
        self.assertEqual(response[1].target, "2_custom_event_3!")
        self.assertEqual(response[1].value, 1)

        self.assertEqual(response[2].source, "1_custom_event_2!")
        self.assertEqual(response[2].target, "2_custom_event_1!")
        self.assertEqual(response[2].value, 1)

        self.assertEqual(response[3].source, "2_custom_event_2!", response[3])
        self.assertEqual(response[3].target, "3_custom_event_3!")
        self.assertEqual(response[3].value, 1)

    def test_screen_paths(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person_1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_2a", "person_2b"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_4"])

        (
            _create_event(
                properties={"$screen_name": "/"},
                distinct_id="person_1",
                event="$screen",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/about"},
                distinct_id="person_1",
                event="$screen",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/"},
                distinct_id="person_2b",
                event="$screen",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/pricing"},
                distinct_id="person_2a",
                event="$screen",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/about"},
                distinct_id="person_2b",
                event="$screen",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/pricing"},
                distinct_id="person_3",
                event="$screen",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/"},
                distinct_id="person_3",
                event="$screen",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/"},
                distinct_id="person_4",
                event="$screen",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$screen_name": "/pricing"},
                distinct_id="person_4",
                event="$screen",
                team=self.team,
            ),
        )

        r = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "pathsFilter": {
                    "includeEventTypes": ["$screen"],
                },
            },
            team=self.team,
        ).run()
        assert isinstance(r, CachedPathsQueryResponse)
        response = r.results

        self.assertEqual(response[0].source, "1_/", response)
        self.assertEqual(response[0].target, "2_/pricing")
        self.assertEqual(response[0].value, 2)

        self.assertEqual(response[1].source, "1_/")
        self.assertEqual(response[1].target, "2_/about")
        self.assertEqual(response[1].value, 1)

        self.assertEqual(response[2].source, "1_/pricing")
        self.assertEqual(response[2].target, "2_/")
        self.assertEqual(response[2].value, 1)

        self.assertEqual(response[3].source, "2_/pricing", response[3])
        self.assertEqual(response[3].target, "3_/about")
        self.assertEqual(response[3].value, 1)

    def test_paths_properties_filter(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person_1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_4"])

        (
            _create_event(
                properties={"$current_url": "/", "$browser": "Chrome"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about", "$browser": "Chrome"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/", "$browser": "Chrome"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/pricing", "$browser": "Chrome"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about", "$browser": "Chrome"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/pricing"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_4",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/pricing"},
                distinct_id="person_4",
                event="$pageview",
                team=self.team,
            ),
        )

        r = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "pathsFilter": {},
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$browser",
                                    "operator": "exact",
                                    "type": "event",
                                    "value": ["Chrome"],
                                }
                            ],
                        }
                    ],
                },
            },
            team=self.team,
        ).run()
        assert isinstance(r, CachedPathsQueryResponse)
        response = r.results

        self.assertEqual(response[0].source, "1_/")
        self.assertEqual(response[0].target, "2_/about")
        self.assertEqual(response[0].value, 1)

        self.assertEqual(response[1].source, "1_/")
        self.assertEqual(response[1].target, "2_/pricing")
        self.assertEqual(response[1].value, 1)

        self.assertEqual(response[2].source, "2_/pricing")
        self.assertEqual(response[2].target, "3_/about")
        self.assertEqual(response[2].value, 1)

    def test_paths_start(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person_1"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_2"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_3"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_4"])
        _create_person(team_id=self.team.pk, distinct_ids=["person_5a", "person_5b"])

        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/pricing/"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_2",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/pricing"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about/"},
                distinct_id="person_3",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_4",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/pricing/"},
                distinct_id="person_4",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/pricing"},
                distinct_id="person_5a",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_5b",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/pricing/"},
                distinct_id="person_5a",
                event="$pageview",
                team=self.team,
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/help"},
                distinct_id="person_5b",
                event="$pageview",
                team=self.team,
            ),
        )

        r = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "pathsFilter": {
                    "startPoint": "/pricing",
                },
            },
            team=self.team,
        ).run()
        assert isinstance(r, CachedPathsQueryResponse)
        response = r.results

        self.assertEqual(len(response), 5)

        self.assertTrue(
            response[0].dict().items() >= {"source": "1_/pricing", "target": "2_/about", "value": 2}.items()
        )
        self.assertTrue(response[1].dict().items() >= {"source": "1_/pricing", "target": "2_/", "value": 1}.items())
        self.assertTrue(response[2].dict().items() >= {"source": "2_/", "target": "3_/about", "value": 1}.items())
        self.assertTrue(
            response[3].dict().items() >= {"source": "2_/about", "target": "3_/pricing", "value": 1}.items()
        )
        self.assertTrue(response[4].dict().items() >= {"source": "3_/pricing", "target": "4_/help", "value": 1}.items())

        # ensure trailing slashes make no difference
        result = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "pathsFilter": {
                    "startPoint": "/pricing/",
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(len(response), 5)

        self.assertTrue(
            response[0].dict().items() >= {"source": "1_/pricing", "target": "2_/about", "value": 2}.items()
        )
        self.assertTrue(response[1].dict().items() >= {"source": "1_/pricing", "target": "2_/", "value": 1}.items())
        self.assertTrue(response[2].dict().items() >= {"source": "2_/", "target": "3_/about", "value": 1}.items())
        self.assertTrue(
            response[3].dict().items() >= {"source": "2_/about", "target": "3_/pricing", "value": 1}.items()
        )
        self.assertTrue(response[4].dict().items() >= {"source": "3_/pricing", "target": "4_/help", "value": 1}.items())

        result = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "pathsFilter": {
                    "startPoint": "/",
                },
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(len(response), 3)

        self.assertTrue(response[0].dict().items() >= {"source": "1_/", "target": "2_/about", "value": 2}.items())
        self.assertTrue(response[1].dict().items() >= {"source": "1_/", "target": "2_/pricing", "value": 2}.items())
        self.assertTrue(
            response[2].dict().items() >= {"source": "2_/pricing", "target": "3_/about", "value": 1}.items()
        )

    def test_paths_in_window(self):
        _create_person(team_id=self.team.pk, distinct_ids=["person_1"])

        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2020-04-14 03:25:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2020-04-14 03:30:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2020-04-15 03:25:34",
            ),
        )
        (
            _create_event(
                properties={"$current_url": "/about"},
                distinct_id="person_1",
                event="$pageview",
                team=self.team,
                timestamp="2020-04-15 03:30:34",
            ),
        )

        date_from = "2020-04-13"
        result = PathsQueryRunner(
            query={
                "kind": "PathsQuery",
                "dateRange": {
                    "date_from": date_from,
                },
                "pathsFilter": {},
            },
            team=self.team,
        ).run()

        assert isinstance(result, CachedPathsQueryResponse)
        response = result.results

        self.assertEqual(response[0].source, "1_/")
        self.assertEqual(response[0].target, "2_/about")
        self.assertEqual(response[0].value, 2)
