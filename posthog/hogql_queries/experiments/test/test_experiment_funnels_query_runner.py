import json
from datetime import datetime, timedelta
from typing import cast

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    BreakdownAttributionType,
    EventsNode,
    ExperimentFunnelsQuery,
    ExperimentSignificanceCode,
    FunnelsQuery,
    PersonsOnEventsMode,
)

from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql_queries.experiments.experiment_funnels_query_runner import ExperimentFunnelsQueryRunner
from posthog.models.experiment import Experiment, ExperimentHoldout
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.test.test_journeys import journeys_for


class TestExperimentFunnelsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def create_feature_flag(self, key="test-experiment"):
        return FeatureFlag.objects.create(
            name=f"Test experiment flag: {key}",
            key=key,
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
            created_by=self.user,
        )

    def create_experiment(self, name="test-experiment", feature_flag=None, start_date=None, end_date=None):
        if feature_flag is None:
            feature_flag = self.create_feature_flag(name)
        if start_date is None:
            start_date = timezone.now()
        else:
            start_date = timezone.make_aware(start_date)  # Make naive datetime timezone-aware
        if end_date is None:
            end_date = timezone.now() + timedelta(days=14)
        elif end_date is not None:
            end_date = timezone.make_aware(end_date)  # Make naive datetime timezone-aware
        return Experiment.objects.create(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=start_date,
            end_date=end_date,
        )

    def create_holdout_for_experiment(self, experiment):
        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Test Experiment holdout",
        )
        holdout.filters = [{"properties": [], "rollout_percentage": 20, "variant": f"holdout-{holdout.id}"}]
        holdout.save()
        experiment.holdout = holdout
        experiment.save()
        return holdout

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            funnels_query=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={feature_flag_property: variant},
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        query_runner = ExperimentFunnelsQueryRunner(
            query=ExperimentFunnelsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        assert len(result.variants) == 2

        control_variant = next(variant for variant in result.variants if variant.key == "control")
        test_variant = next(variant for variant in result.variants if variant.key == "test")

        assert control_variant.success_count == 6
        assert control_variant.failure_count == 4
        assert test_variant.success_count == 8
        assert test_variant.failure_count == 2

        assert result.probability["control"] == pytest.approx(0.2, abs=0.1)
        assert result.probability["test"] == pytest.approx(0.8, abs=0.1)

        assert not result.significant
        assert result.significance_code == ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE
        assert result.expected_loss == 1.0

        assert result.credible_intervals["control"][0] == pytest.approx(0.3, abs=0.1)
        assert result.credible_intervals["control"][1] == pytest.approx(0.8, abs=0.1)
        assert result.credible_intervals["test"][0] == pytest.approx(0.5, abs=0.1)
        assert result.credible_intervals["test"][1] == pytest.approx(0.9, abs=0.1)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_v2(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            funnels_query=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={feature_flag_property: variant},
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        query_runner = ExperimentFunnelsQueryRunner(
            query=ExperimentFunnelsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        assert len(result.variants) == 2

        control_variant = next(variant for variant in result.variants if variant.key == "control")
        test_variant = next(variant for variant in result.variants if variant.key == "test")

        assert control_variant.success_count == 6
        assert control_variant.failure_count == 4
        assert test_variant.success_count == 8
        assert test_variant.failure_count == 2

        assert result.probability["control"] == pytest.approx(0.2, abs=0.1)
        assert result.probability["test"] == pytest.approx(0.8, abs=0.1)

        assert not result.significant
        assert result.significance_code == ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE
        assert result.expected_loss == 1.0

        assert result.credible_intervals["control"][0] == pytest.approx(0.3, abs=0.1)
        assert result.credible_intervals["control"][1] == pytest.approx(0.8, abs=0.1)
        assert result.credible_intervals["test"][0] == pytest.approx(0.5, abs=0.1)
        assert result.credible_intervals["test"][1] == pytest.approx(0.9, abs=0.1)

    @pytest.mark.flaky(reruns=9)
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_standard_flow(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            funnels_query=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                ],
                "user_control_3": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                ],
                "user_test_3": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
                "user_test_4": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentFunnelsQueryRunner(
            query=ExperimentFunnelsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        assert len(result.variants) == 2
        for variant in result.variants:
            assert variant.key in ["control", "test"]

        control_variant = next(v for v in result.variants if v.key == "control")
        test_variant = next(v for v in result.variants if v.key == "test")

        assert control_variant.success_count == 2
        assert control_variant.failure_count == 1
        assert test_variant.success_count == 3
        assert test_variant.failure_count == 1

        assert result.probability["control"] == pytest.approx(0.407, abs=1e-2)
        assert result.probability["test"] == pytest.approx(0.593, abs=1e-2)

        assert result.credible_intervals["control"][0] == pytest.approx(0.1941, abs=1e-3)
        assert result.credible_intervals["control"][1] == pytest.approx(0.9324, abs=1e-3)
        assert result.credible_intervals["test"][0] == pytest.approx(0.2836, abs=1e-3)
        assert result.credible_intervals["test"][1] == pytest.approx(0.9473, abs=1e-3)

        assert result.significance_code == ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE

        assert not result.significant
        assert len(result.variants) == 2
        assert result.expected_loss == pytest.approx(1.0, abs=1e-1)

    @parameterized.expand(
        [
            [
                BreakdownAttributionType.FIRST_TOUCH,
                # 8 total
                {
                    "control_success": 3,
                    "control_failure": 1,
                    "test_success": 3,
                    "test_failure": 1,
                },
            ],
            [
                BreakdownAttributionType.LAST_TOUCH,
                # 8 total
                {
                    "control_success": 3,
                    "control_failure": 1,
                    "test_success": 3,
                    "test_failure": 1,
                },
            ],
            [
                BreakdownAttributionType.ALL_EVENTS,
                # 9 total (one duplicated)
                {
                    "control_success": 3,
                    "control_failure": 1,
                    "test_success": 3,
                    "test_failure": 2,
                },
            ],
            [
                BreakdownAttributionType.STEP,
                # 7 total
                {
                    "control_success": 3,
                    "control_failure": 0,
                    "test_success": 4,
                    "test_failure": 1,
                },
            ],
        ]
    )
    @freeze_time("2020-01-01T00:00:00Z")
    def test_query_runner_attribution(self, attribution_type, expected_counts):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        # use the second step when testing step attribution
        attribution_value = 1 if attribution_type == BreakdownAttributionType.STEP else 0

        ff_property = f"$feature/{feature_flag.key}"
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="seen"), EventsNode(event="signup"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
            funnelsFilter={
                "breakdownAttributionType": attribution_type,
                "breakdownAttributionValue": attribution_value,
                "funnelVizType": "steps",
                "funnelWindowInterval": "14",
                "funnelWindowIntervalUnit": "day",
                "layout": "horizontal",
            },
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            funnels_query=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                # control success always
                "user_control_1": [
                    {"event": "seen", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "signup", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                    {"event": "purchase", "timestamp": "2020-01-04", "properties": {ff_property: "control"}},
                ],
                # control failure for "first_touch", "last_touch", and "all_events"
                # dropped for "steps"
                "user_control_2": [
                    {"event": "seen", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    # Doesn't sign up or make a purchase
                ],
                # control success always
                "user_control_3": [
                    {"event": "seen", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "signup", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                    {"event": "purchase", "timestamp": "2020-01-04", "properties": {ff_property: "control"}},
                ],
                # control success for "first_touch", "last_touch"
                # counted twice for for "all_events"
                # test success for "steps"
                "user_mixed_4": [
                    {"event": "seen", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "seen", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "signup", "timestamp": "2020-01-04", "properties": {ff_property: "control"}},
                    {"event": "signup", "timestamp": "2020-01-05", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-06", "properties": {ff_property: "control"}},
                ],
                # test success always
                "user_test_5": [
                    {"event": "seen", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "signup", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-04", "properties": {ff_property: "test"}},
                ],
                # test success always
                "user_test_6": [
                    {"event": "seen", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "signup", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-04", "properties": {ff_property: "test"}},
                ],
                # test failure always
                "user_test_7": [
                    {"event": "seen", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "signup", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    # Doesn't make a purchase
                ],
                # test success always
                "user_test_8": [
                    {"event": "seen", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "signup", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-04", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentFunnelsQueryRunner(
            query=ExperimentFunnelsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        assert len(result.variants) == 2
        control_variant = next(v for v in result.variants if v.key == "control")
        test_variant = next(v for v in result.variants if v.key == "test")

        assert control_variant.success_count == expected_counts["control_success"]
        assert control_variant.failure_count == expected_counts["control_failure"]
        assert test_variant.success_count == expected_counts["test_success"]
        assert test_variant.failure_count == expected_counts["test_failure"]

    @parameterized.expand(
        [
            ###
            # PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ###
            [
                "person_id_override_properties_on_events_no_filter",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                None,
                {
                    "control_success": 1,
                    "control_failure": 0,
                    "test_success": 1,
                    "test_failure": 0,
                },
            ],
            [
                "person_id_override_properties_on_events_filter_earlierevent",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                {
                    "key": "email",
                    "value": "@earlierevent.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "control_success": 1,
                    "control_failure": 0,
                    "test_success": 1,
                    "test_failure": 0,
                },
            ],
            [
                "person_id_override_properties_on_events_filter_laterevent",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                {
                    "key": "email",
                    "value": "@laterevent.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "control_success": 1,
                    "control_failure": 0,
                    "test_success": 0,
                    "test_failure": 1,
                },
            ],
            ###
            # PERSON_ID_OVERRIDE_PROPERTIES_JOINED
            ###
            [
                "person_id_override_properties_joined_no_filter",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                None,
                {
                    "control_success": 1,
                    "control_failure": 0,
                    "test_success": 1,
                    "test_failure": 0,
                },
            ],
            [
                "person_id_override_properties_joined_filter_earlierevent",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                {
                    "key": "email",
                    "value": "@earlierevent.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "control_success": 1,
                    "control_failure": 0,
                    "test_success": 1,
                    "test_failure": 0,
                },
            ],
            [
                "person_id_override_properties_joined_filter_laterevent",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                {
                    "key": "email",
                    "value": "@laterevent.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                None,
            ],
            ###
            # PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
            ###
            [
                "person_id_no_override_properties_on_events_no_filter",
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                None,
                {
                    "control_success": 1,
                    "control_failure": 0,
                    "test_success": 1,
                    "test_failure": 1,
                },
            ],
            [
                "person_id_no_override_properties_on_events_filter_earlierevent",
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                {
                    "key": "email",
                    "value": "@earlierevent.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "control_success": 1,
                    "control_failure": 0,
                    "test_success": 1,
                    "test_failure": 0,
                },
            ],
            [
                "person_id_no_override_properties_on_events_filter_laterevent",
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                {
                    "key": "email",
                    "value": "@laterevent.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "control_success": 1,
                    "control_failure": 0,
                    "test_success": 0,
                    "test_failure": 1,
                },
            ],
        ]
    )
    @snapshot_clickhouse_queries
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_persons_on_events_mode(self, name, persons_on_events_mode, filters, expected_results):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-31"},
            filterTestAccounts=True,
        )

        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            funnels_query=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        ## Control isn't affected by the filter
        _create_person(distinct_ids=["user_control_1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_control_1",
            timestamp="2020-01-02T12:00:00Z",
            properties={feature_flag_property: "control"},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_control_1",
            timestamp="2020-01-02T12:01:00Z",
            properties={feature_flag_property: "control"},
        )

        ## Test is tied to person on events mode
        _create_person(
            distinct_ids=["person_id_1_distinct_id_1"],
            properties={"email": "person_id_1@earlierevent.com"},
            team_id=self.team.pk,
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person_id_1_distinct_id_1",
            timestamp="2020-01-02T12:00:00Z",
            properties={feature_flag_property: "test"},
        )
        _create_person(
            distinct_ids=["person_id_1_distinct_id_2"],
            properties={"email": "person_id_1@laterevent.com"},
            team_id=self.team.pk,
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person_id_1_distinct_id_2",
            timestamp="2020-01-02T12:01:00Z",
            properties={feature_flag_property: "test"},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="person_id_1_distinct_id_2",
            timestamp="2020-01-02T12:02:00Z",
            properties={feature_flag_property: "test"},
        )
        create_person_id_override_by_distinct_id("person_id_1_distinct_id_1", "person_id_1_distinct_id_2", self.team.pk)

        flush_persons_and_events()

        self.team.modifiers = {"personsOnEventsMode": persons_on_events_mode}
        if filters:
            self.team.test_account_filters = [filters]
        self.team.save()

        query_runner = ExperimentFunnelsQueryRunner(
            query=ExperimentFunnelsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        if expected_results is None:
            with pytest.raises(ValidationError):
                query_runner.calculate()
        else:
            result = query_runner.calculate()

            assert len(result.variants) == 2
            control_variant = next(v for v in result.variants if v.key == "control")
            test_variant = next(v for v in result.variants if v.key == "test")

            assert {
                "control_success": int(control_variant.success_count),
                "control_failure": int(control_variant.failure_count),
                "test_success": int(test_variant.success_count),
                "test_failure": int(test_variant.failure_count),
            } == expected_results

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_holdout(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        holdout = self.create_holdout_for_experiment(experiment)

        feature_flag_property = f"$feature/{feature_flag.key}"

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            funnels_query=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        for variant, purchase_count in [("control", 6), ("test", 8), (f"holdout-{holdout.id}", 3)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={feature_flag_property: variant},
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        query_runner = ExperimentFunnelsQueryRunner(
            query=ExperimentFunnelsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        assert len(result.variants) == 3

        control_variant = next(variant for variant in result.variants if variant.key == "control")
        test_variant = next(variant for variant in result.variants if variant.key == "test")
        holdout_variant = next(variant for variant in result.variants if variant.key == f"holdout-{holdout.id}")

        assert control_variant.success_count == 6
        assert control_variant.failure_count == 4
        assert test_variant.success_count == 8
        assert test_variant.failure_count == 2
        assert holdout_variant.success_count == 3
        assert holdout_variant.failure_count == 7

        assert "control" in result.probability
        assert "test" in result.probability
        assert f"holdout-{holdout.id}" in result.probability

        assert "control" in result.credible_intervals
        assert "test" in result.credible_intervals
        assert f"holdout-{holdout.id}" in result.credible_intervals

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_control(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        journeys_for(
            {
                "user_test": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            funnels_query=funnels_query,
        )

        query_runner = ExperimentFunnelsQueryRunner(query=experiment_query, team=self.team)
        with pytest.raises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: False,
            }
        )
        assert cast(list, context.value.detail)[0] == expected_errors

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_test(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        journeys_for(
            {
                "user_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "purchase", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
        )
        experiment_query = ExperimentFunnelsQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelsQuery",
            funnels_query=funnels_query,
        )

        query_runner = ExperimentFunnelsQueryRunner(query=experiment_query, team=self.team)
        with pytest.raises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: False,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        assert cast(list, context.value.detail)[0] == expected_errors
