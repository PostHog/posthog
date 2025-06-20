import json
from datetime import datetime
from typing import cast

from django.test import override_settings
from freezegun import freeze_time
from parameterized import parameterized
from pytest import mark
from rest_framework.exceptions import ValidationError

from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql_queries.experiments.experiment_query_runner import (
    ExperimentQueryRunner,
)
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import (
    ExperimentQueryRunnerBaseTest,
)
from posthog.hogql_queries.experiments.test.experiment_query_runner.utils import (
    create_standard_group_test_events,
)
from posthog.models.action.action import Action
from posthog.schema import (
    ActionsNode,
    EventPropertyFilter,
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentQuery,
    ExperimentVariantFunnelsBaseStats,
    FunnelConversionWindowTimeUnit,
    LegacyExperimentQueryResponse,
    PersonsOnEventsMode,
    PropertyOperator,
    StepOrderValue,
)
from posthog.test.base import (
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentFunnelMetric(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_funnel_metric(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

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
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

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
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

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
            conversion_window=24,
            conversion_window_unit=FunnelConversionWindowTimeUnit.HOUR,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

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

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_duplicate_events(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                # User with two pageviews and second step completed, should be included.
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
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:05:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:06:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User with all duplicated events, should be included.
                "user_control_2": [
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
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03T12:00:30",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03T12:02:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:03:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03T12:04:00",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:05:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:06:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User with wrong order completed. Should be excluded.
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
                        "event": "purchase",
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                # User with duplicate events in wrong order. Should be excluded.
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
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:03:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:04:00",
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.success_count, 2)
        self.assertEqual(control_variant.failure_count, 0)
        self.assertEqual(test_variant.success_count, 0)
        self.assertEqual(test_variant.failure_count, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_events_out_of_order(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                # User with events out of order but with complete funnel. Should be included.
                "user_control_1": [
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
                        "timestamp": "2024-01-03T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:03:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User with events out of order but complete funnel. Should be included.
                "user_control_2": [
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
                        "timestamp": "2024-01-03T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:02:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:03:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:04:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User with wrong order completed. Should be excluded.
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
                        "event": "purchase",
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                # User with experiment exposure after completing the funnel. Should be excluded.
                "user_test_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:00:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:01:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03T12:02:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03T12:03:00",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.success_count, 2)
        self.assertEqual(control_variant.failure_count, 0)
        self.assertEqual(test_variant.success_count, 0)
        self.assertEqual(test_variant.failure_count, 2)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_many_steps(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
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
                    {
                        "event": "add to cart",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "checkout started",
                        "timestamp": "2024-01-02T12:03:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "checkout completed",
                        "timestamp": "2024-01-02T12:04:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "survey submitted",
                        "timestamp": "2024-01-02T12:05:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "referral",
                        "timestamp": "2024-01-02T12:06:00",
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
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="add to cart"),
                EventsNode(event="checkout started"),
                EventsNode(event="checkout completed"),
                EventsNode(event="survey submitted"),
                EventsNode(event="referral"),
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.success_count, 1)
        self.assertEqual(control_variant.failure_count, 0)
        self.assertEqual(test_variant.success_count, 0)
        self.assertEqual(test_variant.failure_count, 1)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_step_property_filter(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                # User with complete funnel, should be included.
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
                            "wizard_step": "step_1",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "control",
                            "wizard_step": "step_2",
                        },
                    },
                ],
                # User with incomplete funnel. Should be excluded.
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
                            "wizard_step": "step_1",
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(
                    event="$pageview",
                    properties=[
                        EventPropertyFilter(
                            key="wizard_step", operator=PropertyOperator.EXACT, value="step_1", type="event"
                        ),
                    ],
                ),
                EventsNode(
                    event="$pageview",
                    properties=[
                        EventPropertyFilter(
                            key="wizard_step",
                            operator=PropertyOperator.EXACT,
                            value="step_2",
                            type="event",
                        ),
                    ],
                ),
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.success_count, 1)
        self.assertEqual(control_variant.failure_count, 0)
        self.assertEqual(test_variant.success_count, 0)
        self.assertEqual(test_variant.failure_count, 1)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_multiple_similar_steps(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                # User with complete funnel, should be included.
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
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03T12:05:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02T12:06:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User with only a single purchase. Should be excluded.
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
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="purchase"),
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.success_count, 1)
        self.assertEqual(control_variant.failure_count, 0)
        self.assertEqual(test_variant.success_count, 0)
        self.assertEqual(test_variant.failure_count, 1)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_unordered_steps(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                # User completes steps in reverse order - should succeed with unordered funnel
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
                        "event": "purchase",
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User completes steps in mixed order - should succeed with unordered funnel
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
                        "event": "add_to_cart",
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02T12:03:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # User completes only first step - should fail
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
                # User completes steps out of order - should succeed with unordered funnel
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
                        "event": "purchase",
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "add_to_cart",
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02T12:03:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        # Create funnel metric with unordered steps (simplified to 2 steps for debugging)
        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="purchase"),
            ],
            funnel_order_type=StepOrderValue.UNORDERED,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantFunnelsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        # With unordered 2-step funnel ($pageview + purchase), both control users should succeed
        # (completed both steps in any order) and test user 2 should succeed (completed both steps),
        # test user 1 should fail (only has $pageview, missing purchase)
        self.assertEqual(control_variant.success_count, 2)
        self.assertEqual(control_variant.failure_count, 0)
        self.assertEqual(test_variant.success_count, 1)
        self.assertEqual(test_variant.failure_count, 1)

    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_ordered_vs_unordered_comparison(self):
        """Test that ordered and unordered funnels behave differently when events are out of order"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data where events occur in reverse order
        journeys_for(
            {
                # Control user completes steps in reverse order
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
                        "event": "purchase",  # step 2 happens first
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                    {
                        "event": "$pageview",  # step 1 happens second
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                # Test user completes steps in reverse order
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
                        "event": "purchase",  # step 2 happens first
                        "timestamp": "2024-01-02T12:01:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                    {
                        "event": "$pageview",  # step 1 happens second
                        "timestamp": "2024-01-02T12:02:00",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        # Test with ordered funnel (should fail)
        ordered_metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="purchase"),
            ],
            funnel_order_type=StepOrderValue.ORDERED,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=ordered_metric,
        )

        experiment.metrics = [ordered_metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        ordered_result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        # Test with unordered funnel (should succeed)
        unordered_metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="purchase"),
            ],
            funnel_order_type=StepOrderValue.UNORDERED,
        )

        experiment_query.metric = unordered_metric
        experiment.metrics = [unordered_metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        unordered_result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        # With ordered funnel, the out-of-order events should not be counted as success
        ordered_control = cast(
            ExperimentVariantFunnelsBaseStats,
            next(variant for variant in ordered_result.variants if variant.key == "control"),
        )
        ordered_test = cast(
            ExperimentVariantFunnelsBaseStats,
            next(variant for variant in ordered_result.variants if variant.key == "test"),
        )

        # With unordered funnel, the out-of-order events should be counted as success
        unordered_control = cast(
            ExperimentVariantFunnelsBaseStats,
            next(variant for variant in unordered_result.variants if variant.key == "control"),
        )
        unordered_test = cast(
            ExperimentVariantFunnelsBaseStats,
            next(variant for variant in unordered_result.variants if variant.key == "test"),
        )

        # Ordered should fail (0 success) because events are out of order
        self.assertEqual(ordered_control.success_count, 0)
        self.assertEqual(ordered_control.failure_count, 1)
        self.assertEqual(ordered_test.success_count, 0)
        self.assertEqual(ordered_test.failure_count, 1)

        # Unordered should succeed (1 success) because order doesn't matter
        self.assertEqual(unordered_control.success_count, 1)
        self.assertEqual(unordered_control.failure_count, 0)
        self.assertEqual(unordered_test.success_count, 1)
        self.assertEqual(unordered_test.failure_count, 0)
