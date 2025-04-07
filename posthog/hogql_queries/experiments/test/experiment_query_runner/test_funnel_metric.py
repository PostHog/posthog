import json
from typing import cast
from django.test import override_settings
from pytest import mark
from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.utils import (
    create_standard_group_test_events,
)
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from rest_framework.exceptions import ValidationError
from posthog.models.action.action import Action
from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentQuery,
    ExperimentVariantFunnelsBaseStats,
    PersonsOnEventsMode,
    ExperimentFunnelMetric,
)
from posthog.test.base import (
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from freezegun import freeze_time
from datetime import datetime
from posthog.test.test_journeys import journeys_for
from parameterized import parameterized


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentQueryRunner(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_funnel_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"version": 2}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="purchase"),
            ],
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        self.create_standard_test_events(feature_flag)

        # Extra success events that should be ignored
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_control_1",
            timestamp="2020-01-03T12:01:00Z",
            properties={feature_flag_property: "control"},
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_1",
            timestamp="2020-01-03T12:01:00Z",
            properties={feature_flag_property: "test"},
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.success_count, 6)
        self.assertEqual(control_variant.failure_count, 4)
        self.assertEqual(test_variant.success_count, 8)
        self.assertEqual(test_variant.failure_count, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_group_aggregation_funnel_metric(self):
        feature_flag = self.create_feature_flag()
        feature_flag.filters["aggregation_group_type_index"] = 0
        feature_flag.save()
        experiment = self.create_experiment(feature_flag=feature_flag)

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="purchase"),
            ],
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        create_standard_group_test_events(self.team, feature_flag)

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.success_count, 2)
        self.assertEqual(test_variant.success_count, 3)
        self.assertEqual(control_variant.failure_count, 0)
        self.assertEqual(test_variant.failure_count, 0)

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
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 1, 31),
        )
        experiment.stats_config = {"version": 2}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=ExperimentFunnelMetric(
                series=[
                    EventsNode(event="purchase"),
                ],
            ),
        )
        experiment.exposure_criteria = {"filterTestAccounts": True}
        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        ## Control isn't affected by the filter
        _create_person(distinct_ids=["user_control_1"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_control_1",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                "$feature_flag": feature_flag.key,
                feature_flag_property: "control",
                "$feature_flag_response": "control",
            },
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
            event="$feature_flag_called",
            distinct_id="person_id_1_distinct_id_1",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                "$feature_flag": feature_flag.key,
                feature_flag_property: "test",
                "$feature_flag_response": "test",
            },
        )
        _create_person(
            distinct_ids=["person_id_1_distinct_id_2"],
            properties={"email": "person_id_1@laterevent.com"},
            team_id=self.team.pk,
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="person_id_1_distinct_id_2",
            timestamp="2020-01-02T12:01:00Z",
            properties={
                "$feature_flag": feature_flag.key,
                feature_flag_property: "test",
                "$feature_flag_response": "test",
            },
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

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        if expected_results is None:
            with self.assertRaises(ValidationError) as context:
                query_runner.calculate()

            if "person_id_override_properties_joined_filter_laterevent" in name:
                expected_errors = json.dumps(
                    {
                        ExperimentNoResultsErrorKeys.NO_EXPOSURES: False,
                        ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: False,
                        ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
                    }
                )
            else:
                expected_errors = json.dumps(
                    {
                        ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
                        ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                        ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
                    }
                )
            self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)
        else:
            result = query_runner.calculate()

            self.assertEqual(len(result.variants), 2)
            control_variant = cast(
                ExperimentVariantFunnelsBaseStats, next(v for v in result.variants if v.key == "control")
            )
            test_variant = cast(ExperimentVariantFunnelsBaseStats, next(v for v in result.variants if v.key == "test"))

            self.assertEqual(
                {
                    "control_success": int(control_variant.success_count),
                    "control_failure": int(control_variant.failure_count),
                    "test_success": int(test_variant.success_count),
                    "test_failure": int(test_variant.failure_count),
                },
                expected_results,
            )

    @mark.skip("Funnel metrics on data warehouse tables are not supported yet")
    @snapshot_clickhouse_queries
    def test_query_runner_data_warehouse_funnel_metric(self):
        # table_name = self.create_data_warehouse_table_with_usage()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2023, 1, 1), end_date=datetime(2023, 1, 31)
        )
        experiment.stats_config = {"version": 2}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentFunnelMetric(
            # TODO: fix this once supported
            # source=ExperimentDataWarehouseNode(
            #     table_name=table_name,
            #     events_join_key="properties.$user_id",
            #     data_warehouse_join_key="userid",
            #     timestamp_field="ds",
            # ),
            series=[
                EventsNode(event="purchase"),
            ],
        )
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )
        experiment.exposure_criteria = {"filterTestAccounts": False}
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"distinct_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                        "$user_id": f"user_{variant}_{i}",
                        "$group_0": "my_awesome_group",
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_result = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_result = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_result.success_count, 1)
        self.assertEqual(test_result.success_count, 3)
        self.assertEqual(control_result.failure_count, 6)
        self.assertEqual(test_result.failure_count, 6)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_conversion_window(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"version": 2}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                # User completes both steps within default conversion window (experiment duration)
                "user_control_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T13:00:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-08T11:00:00",  # Within default conversion window (experiment duration)
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User completes first step but second step is outside conversion window
                "user_control_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T13:00:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-16T14:00:00",  # Outside default conversion window (experiment duration)
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # Test variant: completes both steps within window
                "user_test_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T13:00:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-08T12:30:00",  # Within default conversion window (experiment duration)
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                # Test variant: completes first step but second step outside window
                "user_test_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T13:00:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-16T15:00:00",  # Outside default conversion window (experiment duration)
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        # Create funnel metric with default conversion window (experiment duration)
        # (by not specifying time_window_hours)
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="purchase"),
            ],
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        # Only events within the conversion window should be counted as successes
        self.assertEqual(control_variant.success_count, 1)
        self.assertEqual(control_variant.failure_count, 1)
        self.assertEqual(test_variant.success_count, 1)
        self.assertEqual(test_variant.failure_count, 1)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_custom_conversion_window(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"version": 2}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                # User completes both steps within custom conversion window (24 hours)
                "user_control_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T13:00:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T10:00:00",  # Within 24 hours of pageview
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User completes first step but second step is outside conversion window
                "user_control_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T13:00:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T14:00:00",  # Outside 24 hours window (25 hours after pageview)
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # Test variant: completes both steps within window
                "user_test_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T13:00:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T10:30:00",  # Within 24 hours of pageview
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                # Test variant: completes first step but second step outside window
                "user_test_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T13:00:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T15:00:00",  # Outside 24 hours window
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        # Create funnel metric with custom 24 hours conversion window
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="purchase"),
            ],
            time_window_hours=24,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        # Only events within the custom conversion window should be counted as successes
        self.assertEqual(control_variant.success_count, 1)
        self.assertEqual(control_variant.failure_count, 1)
        self.assertEqual(test_variant.success_count, 1)
        self.assertEqual(test_variant.failure_count, 1)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_action(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"version": 2}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                # User with first step only
                "user_control_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User with first and second step completed
                "user_control_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:02:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User with second step only
                "user_control_3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03T12:00:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:02:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User with only first step completed
                "user_test_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                # User with whole funnel completed
                "user_test_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:01:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:02:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                # User with only feature flag and purchase, no pageview. Should be excluded.
                "user_test_3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02T12:00:00",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:02:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        action = Action.objects.create(name="purchase action", team=self.team, steps_json=[{"event": "purchase"}])
        action.save()

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                ActionsNode(id=action.id),
            ],
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.success_count, 1)
        self.assertEqual(control_variant.failure_count, 2)
        self.assertEqual(test_variant.success_count, 1)
        self.assertEqual(test_variant.failure_count, 2)
