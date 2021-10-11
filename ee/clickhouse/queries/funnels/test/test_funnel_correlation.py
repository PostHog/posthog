import unittest
from uuid import uuid4

from rest_framework.exceptions import ValidationError

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_correlation import EventContingencyTable, EventStats, FunnelCorrelation
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest, BaseTest, test_with_materialized_columns


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseFunnelCorrelation(ClickhouseTestMixin, APIBaseTest):

    maxDiff = None

    def test_basic_funnel_correlation_with_events(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        result = correlation.run()["events"]

        odds_ratios = [item.pop("odds_ratio") for item in result]  # type: ignore
        expected_odds_ratios = [11, 1 / 11]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related",
                    "success_count": 5,
                    "failure_count": 0,
                    # "odds_ratio": 11.0,
                    "correlation_type": "success",
                },
                {
                    "event": "negatively_related",
                    "success_count": 0,
                    "failure_count": 5,
                    # "odds_ratio": 1 / 11,
                    "correlation_type": "failure",
                },
            ],
        )

    @test_with_materialized_columns(event_properties=[], person_properties=["$browser"])
    def test_basic_funnel_correlation_with_properties(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "properties",
            "funnel_correlation_names": ["$browser"],
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Positive"})
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Negative"})
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        # One Positive with failure
        _create_person(distinct_ids=[f"user_fail"], team_id=self.team.pk, properties={"$browser": "Positive"})
        _create_event(
            team=self.team, event="user signed up", distinct_id=f"user_fail", timestamp="2020-01-02T14:00:00Z",
        )

        # One Negative with success
        _create_person(distinct_ids=[f"user_succ"], team_id=self.team.pk, properties={"$browser": "Negative"})
        _create_event(
            team=self.team, event="user signed up", distinct_id=f"user_succ", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id=f"user_succ", timestamp="2020-01-04T14:00:00Z",
        )

        result = correlation.run()["events"]

        odds_ratios = [item.pop("odds_ratio") for item in result]  # type: ignore

        # Success Total = 11, Failure Total = 11
        #
        # Browser::Positive
        # Success: 10
        # Failure: 1

        # Browser::Negative
        # Success: 1
        # Failure: 10

        prior_count = 1
        expected_odds_ratios = [
            ((10 + prior_count) / (1 + prior_count)) * ((11 - 1 + prior_count) / (11 - 10 + prior_count)),
            ((1 + prior_count) / (10 + prior_count)) * ((11 - 10 + prior_count) / (11 - 1 + prior_count)),
        ]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "$browser::Positive",
                    "success_count": 10,
                    "failure_count": 1,
                    # "odds_ratio": 121/4,
                    "correlation_type": "success",
                },
                {
                    "event": "$browser::Negative",
                    "success_count": 1,
                    "failure_count": 10,
                    # "odds_ratio": 4/121,
                    "correlation_type": "failure",
                },
            ],
        )

    def test_no_divide_by_zero_errors(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        for i in range(2):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Positive"})
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            # failure count for this event is 0
            _create_event(
                team=self.team, event="positive", distinct_id=f"user_{i}", timestamp="2020-01-03T14:00:00Z",
            )
            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(2, 4):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Negative"})
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                # success count for this event is 0
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        results = correlation.run()
        self.assertFalse(results["skewed"])

        result = results["events"]

        odds_ratios = [item.pop("odds_ratio") for item in result]  # type: ignore
        expected_odds_ratios = [9, 1 / 3]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positive",
                    "success_count": 2,
                    "failure_count": 0,
                    # "odds_ratio": 9.0,
                    "correlation_type": "success",
                },
                {
                    "event": "negatively_related",
                    "success_count": 0,
                    "failure_count": 1,
                    # "odds_ratio": 1 / 3,
                    "correlation_type": "failure",
                },
            ],
        )

    def test_correlation_with_properties_raises_validation_error(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "properties",
            # "funnel_correlation_names": ["$browser"], missing value
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        _create_person(distinct_ids=[f"user_1"], team_id=self.team.pk, properties={"$browser": "Positive"})
        _create_event(
            team=self.team, event="user signed up", distinct_id=f"user_1", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id=f"user_1", timestamp="2020-01-04T14:00:00Z",
        )

        with self.assertRaises(ValidationError):
            correlation.run()

    @test_with_materialized_columns(event_properties=[], person_properties=["$browser"])
    def test_correlation_with_multiple_properties(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "properties",
            "funnel_correlation_names": ["$browser", "$nice"],
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        #  5 successful people with both properties
        for i in range(5):
            _create_person(
                distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Positive", "$nice": "very"}
            )
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        #  10 successful people with some different properties
        for i in range(5, 15):
            _create_person(
                distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Positive", "$nice": "not"}
            )
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        # 5 Unsuccessful people with some common properties
        for i in range(15, 20):
            _create_person(
                distinct_ids=[f"user_{i}"], team_id=self.team.pk, properties={"$browser": "Negative", "$nice": "smh"}
            )
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )

        # One Positive with failure, no $nice property
        _create_person(distinct_ids=[f"user_fail"], team_id=self.team.pk, properties={"$browser": "Positive"})
        _create_event(
            team=self.team, event="user signed up", distinct_id=f"user_fail", timestamp="2020-01-02T14:00:00Z",
        )

        # One Negative with success, no $nice property
        _create_person(distinct_ids=[f"user_succ"], team_id=self.team.pk, properties={"$browser": "Negative"})
        _create_event(
            team=self.team, event="user signed up", distinct_id=f"user_succ", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id=f"user_succ", timestamp="2020-01-04T14:00:00Z",
        )

        result = correlation.run()["events"]

        # Success Total = 5 + 10 + 1 = 16
        # Failure Total = 5 + 1 = 6
        # Add 1 for priors

        odds_ratios = [item.pop("odds_ratio") for item in result]  # type: ignore
        expected_odds_ratios = [
            (16 / 2) * ((7 - 1) / (17 - 15)),
            (11 / 1) * ((7 - 0) / (17 - 10)),
            (6 / 1) * ((7 - 0) / (17 - 5)),
            (1 / 6) * ((7 - 5) / (17 - 0)),
            (2 / 6) * ((7 - 5) / (17 - 1)),
            (2 / 2) * ((7 - 1) / (17 - 1)),
        ]
        # (success + 1) / (failure + 1)

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        expected_result = [
            {
                "event": "$browser::Positive",
                "success_count": 15,
                "failure_count": 1,
                # "odds_ratio": 24,
                "correlation_type": "success",
            },
            {
                "event": "$nice::not",
                "success_count": 10,
                "failure_count": 0,
                # "odds_ratio": 11,
                "correlation_type": "success",
            },
            {
                "event": "$nice::very",
                "success_count": 5,
                "failure_count": 0,
                # "odds_ratio": 3.5,
                "correlation_type": "success",
            },
            {
                "event": "$nice::smh",
                "success_count": 0,
                "failure_count": 5,
                # "odds_ratio": 0.0196078431372549,
                "correlation_type": "failure",
            },
            {
                "event": "$browser::Negative",
                "success_count": 1,
                "failure_count": 5,
                # "odds_ratio": 0.041666666666666664,
                "correlation_type": "failure",
            },
            {
                "event": "$nice::",
                "success_count": 1,
                "failure_count": 1,
                # "odds_ratio": 0.375,
                "correlation_type": "failure",
            },
        ]

        self.assertEqual(result, expected_result)

        # Run property correlation with filter on all properties
        filter = filter.with_data({"funnel_correlation_names": ["$all"]})
        correlation = FunnelCorrelation(filter, self.team)

        new_result = correlation.run()["events"]

        odds_ratios = [item.pop("odds_ratio") for item in new_result]  # type: ignore

        new_expected_odds_ratios = expected_odds_ratios[:-1]
        new_expected_result = expected_result[:-1]
        # When querying all properties, we don't consider properties that don't exist for part of the data
        # since users aren't explicitly asking for that property. Thus,
        # We discard $nice:: because it's an empty result set

        for odds, expected_odds in zip(odds_ratios, new_expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(new_result, new_expected_result)

    def test_discarding_insignificant_events(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        for i in range(10):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
            if i % 10 == 0:
                _create_event(
                    team=self.team,
                    event="low_sig_positively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:20:00Z",
                )
            _create_event(
                team=self.team, event="paid", distinct_id=f"user_{i}", timestamp="2020-01-04T14:00:00Z",
            )

        for i in range(10, 20):
            _create_person(distinct_ids=[f"user_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team, event="user signed up", distinct_id=f"user_{i}", timestamp="2020-01-02T14:00:00Z",
            )
            if i % 2 == 0:
                _create_event(
                    team=self.team,
                    event="negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )
            if i % 5 == 0:
                _create_event(
                    team=self.team,
                    event="low_sig_negatively_related",
                    distinct_id=f"user_{i}",
                    timestamp="2020-01-03T14:00:00Z",
                )

        #  Total 10 positive, 10 negative
        # low sig count = 1 and 2, high sig count >= 5
        # Thus, to discard the low sig count, % needs to be >= 10%, or count >= 2

        # Discard both due to %
        FunnelCorrelation.MIN_PERSON_PERCENTAGE = 0.11
        FunnelCorrelation.MIN_PERSON_COUNT = 25
        result = correlation.run()["events"]
        self.assertEqual(len(result), 2)

    def test_events_within_conversion_window_for_correlation(self):
        filters = {
            "events": [
                {"id": "user signed up", "type": "events", "order": 0},
                {"id": "paid", "type": "events", "order": 1},
            ],
            "insight": INSIGHT_FUNNELS,
            "funnel_window_interval": "10",
            "funnel_window_interval_unit": "minute",
            "date_from": "2020-01-01",
            "date_to": "2020-01-14",
            "funnel_correlation_type": "events",
        }

        filter = Filter(data=filters)
        correlation = FunnelCorrelation(filter, self.team)

        _create_person(distinct_ids=["user_successful"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_successful", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team, event="positively_related", distinct_id="user_successful", timestamp="2020-01-02T14:02:00Z",
        )
        _create_event(
            team=self.team, event="paid", distinct_id="user_successful", timestamp="2020-01-02T14:06:00Z",
        )

        _create_person(distinct_ids=["user_dropoff"], team_id=self.team.pk)
        _create_event(
            team=self.team, event="user signed up", distinct_id="user_dropoff", timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="NOT_negatively_related",
            distinct_id="user_dropoff",
            timestamp="2020-01-02T14:15:00Z",  # event happened outside conversion window
        )

        result = correlation.run()["events"]
        print(result)

        odds_ratios = [item.pop("odds_ratio") for item in result]  # type: ignore
        expected_odds_ratios = [4]

        for odds, expected_odds in zip(odds_ratios, expected_odds_ratios):
            self.assertAlmostEqual(odds, expected_odds)

        self.assertEqual(
            result,
            [
                {
                    "event": "positively_related",
                    "success_count": 1,
                    "failure_count": 0,
                    # "odds_ratio": 4.0,
                    "correlation_type": "success",
                },
            ],
        )


class TestCorrelationFunctions(unittest.TestCase):
    def test_are_results_insignificant(self):
        # Same setup as above test: test_discarding_insignificant_events
        contingency_tables = [
            EventContingencyTable(
                event="negatively_related",
                visited=EventStats(success_count=0, failure_count=5),
                success_total=10,
                failure_total=10,
            ),
            EventContingencyTable(
                event="positively_related",
                visited=EventStats(success_count=5, failure_count=0),
                success_total=10,
                failure_total=10,
            ),
            EventContingencyTable(
                event="low_sig_negatively_related",
                visited=EventStats(success_count=0, failure_count=2),
                success_total=10,
                failure_total=10,
            ),
            EventContingencyTable(
                event="low_sig_positively_related",
                visited=EventStats(success_count=1, failure_count=0),
                success_total=10,
                failure_total=10,
            ),
        ]

        # Discard both low_sig due to %
        FunnelCorrelation.MIN_PERSON_PERCENTAGE = 0.11
        FunnelCorrelation.MIN_PERSON_COUNT = 25
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelation.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 2)

        # Discard one low_sig due to %
        FunnelCorrelation.MIN_PERSON_PERCENTAGE = 0.051
        FunnelCorrelation.MIN_PERSON_COUNT = 25
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelation.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 3)

        # Discard both due to count
        FunnelCorrelation.MIN_PERSON_PERCENTAGE = 0.5
        FunnelCorrelation.MIN_PERSON_COUNT = 3
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelation.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 2)

        # Discard one due to count
        FunnelCorrelation.MIN_PERSON_PERCENTAGE = 0.5
        FunnelCorrelation.MIN_PERSON_COUNT = 2
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelation.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 3)

        # Discard everything due to %
        FunnelCorrelation.MIN_PERSON_PERCENTAGE = 0.5
        FunnelCorrelation.MIN_PERSON_COUNT = 100
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelation.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 0)

        # Discard everything due to count
        FunnelCorrelation.MIN_PERSON_PERCENTAGE = 0.5
        FunnelCorrelation.MIN_PERSON_COUNT = 6
        result = [
            1
            for contingency_table in contingency_tables
            if not FunnelCorrelation.are_results_insignificant(contingency_table)
        ]
        self.assertEqual(len(result), 0)
