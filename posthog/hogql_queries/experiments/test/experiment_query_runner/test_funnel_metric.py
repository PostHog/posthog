import json
import uuid
from datetime import datetime
from typing import cast

from freezegun import freeze_time
from posthog.test.base import (
    _create_event,
    _create_person,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from pytest import mark

from django.test import override_settings

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    EventPropertyFilter,
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentQuery,
    FunnelConversionWindowTimeUnit,
    PersonsOnEventsMode,
    PropertyOperator,
    StepOrderValue,
)

from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.hogql_queries.experiments.test.experiment_query_runner.utils import add_query_builder_flag
from posthog.models.action.action import Action
from posthog.models.filters.utils import GroupTypeIndex
from posthog.test.test_utils import create_group_type_mapping_without_created_at


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentFunnelMetric(ExperimentQueryRunnerBaseTest):
    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_funnel_metric(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
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

        # Control: 8 successes, 7 failures (15 total exposures)
        control_success_events = []
        for i in range(15):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "control",
                    "$feature_flag_response": "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            if i < 8:  # First 8 users make purchases
                event_uuid = str(uuid.uuid4())
                control_success_events.append(event_uuid)
                _create_event(
                    team=self.team,
                    event_uuid=event_uuid,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "control", "amount": 10 if i < 2 else ""},
                )

        # Test: 10 successes, 5 failures (15 total exposures)
        for i in range(15):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "test",
                    "$feature_flag_response": "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            if i < 10:  # First 10 users make purchases
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "test", "amount": 10 if i < 2 else ""},
                )

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

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Convert to funnel stats for assertion (sum = success_count, number_of_samples - sum = failure_count)
        self.assertEqual(control_variant.sum, 8)  # success_count
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 7)  # failure_count

        self.assertEqual(test_variant.sum, 10)  # success_count
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 5)  # failure_count

        # Check that we have the correct data for rendering the funnel chart
        self.assertEqual(control_variant.step_counts, [8])  # contains data for funnel chart
        control_sampled_success_events = [s.event_uuid for s in control_variant.step_sessions[1]]
        self.assertEqual(sorted(control_success_events), sorted(control_sampled_success_events))

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_group_aggregation_funnel_metric(self, name, use_new_query_builder):
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
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        # Create test groups with enough variance for Bayesian testing
        from posthog.models.group.util import create_group

        group_type_index: GroupTypeIndex = 0
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=group_type_index,
            group_type="organization",
        )

        # Create many groups
        for i in range(20):
            create_group(
                team_id=self.team.pk,
                group_type_index=group_type_index,
                group_key=f"org:{i}",
                properties={"name": f"org {i}"},
            )

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Control: 10 groups that purchase, 8 that don't (18 total)
        group_idx = 0
        for purchase in [True] * 10 + [False] * 8:
            for user_idx in range(5):  # 5 users per group
                user_id = f"user_control_{group_idx}_{user_idx}"
                _create_person(distinct_ids=[user_id], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=user_id,
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: "control",
                        "$feature_flag_response": "control",
                        "$feature_flag": feature_flag.key,
                        "$group_0": f"org:{group_idx}",
                        "$groups": {"organization": f"org:{group_idx}"},
                    },
                )
                if purchase:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=user_id,
                        timestamp="2020-01-02T12:01:00Z",
                        properties={
                            feature_flag_property: "control",
                            "$group_0": f"org:{group_idx}",
                            "$groups": {"organization": f"org:{group_idx}"},
                        },
                    )
            group_idx += 1

        # Test: 12 groups that purchase, 6 that don't (18 total)
        for purchase in [True] * 12 + [False] * 6:
            for user_idx in range(5):  # 5 users per group
                user_id = f"user_test_{group_idx}_{user_idx}"
                _create_person(distinct_ids=[user_id], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=user_id,
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: "test",
                        "$feature_flag_response": "test",
                        "$feature_flag": feature_flag.key,
                        "$group_0": f"org:{group_idx}",
                        "$groups": {"organization": f"org:{group_idx}"},
                    },
                )
                if purchase:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=user_id,
                        timestamp="2020-01-02T12:01:00Z",
                        properties={
                            feature_flag_property: "test",
                            "$group_0": f"org:{group_idx}",
                            "$groups": {"organization": f"org:{group_idx}"},
                        },
                    )
            group_idx += 1

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 10)  # success_count (10 groups purchase)
        self.assertEqual(test_variant.sum, 12)  # success_count (12 groups purchase)
        self.assertEqual(
            control_variant.number_of_samples - control_variant.sum, 8
        )  # failure_count (8 groups don't purchase)
        self.assertEqual(
            test_variant.number_of_samples - test_variant.sum, 6
        )  # failure_count (6 groups don't purchase)

    @parameterized.expand(
        add_query_builder_flag(
            [
                ###
                # PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
                ###
                [
                    "person_id_override_properties_on_events_no_filter",
                    PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                    None,
                    {
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 8,
                        "test_failure": 5,
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
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 8,
                        "test_failure": 5,
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
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 1,
                        "test_failure": 12,
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
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 8,
                        "test_failure": 5,
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
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 8,
                        "test_failure": 5,
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
                    {
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 8,
                        "test_failure": 5,
                    },
                ],
                ###
                # PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
                ###
                [
                    "person_id_no_override_properties_on_events_no_filter",
                    PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                    None,
                    {
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 8,
                        "test_failure": 5,
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
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 8,
                        "test_failure": 5,
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
                        "control_success": 8,
                        "control_failure": 5,
                        "test_success": 6,
                        "test_failure": 7,
                    },
                ],
            ]
        )
    )
    @snapshot_clickhouse_queries
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_persons_on_events_mode(
        self, name, persons_on_events_mode, filters, expected_results, use_new_query_builder
    ):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2020, 1, 31),
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
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

        ## Control group: create 13 users, 8 purchase (successes), 5 don't purchase (failures)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    "$feature_flag": feature_flag.key,
                    feature_flag_property: "control",
                    "$feature_flag_response": "control",
                },
            )
            if i < 8:  # First 8 users make purchases (successes)
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={feature_flag_property: "control"},
                )

        ## Test group: create users based on person ID override behavior
        # Create 13 pairs of person IDs to test the override functionality
        for i in range(13):
            # Create the "earlier" person (with @earlierevent.com email)
            _create_person(
                distinct_ids=[f"person_id_{i}_distinct_id_1"],
                properties={"email": f"person_id_{i}@earlierevent.com"},
                team_id=self.team.pk,
            )
            # Only create feature flag events for distinct_id_1 in modes that use person ID overrides
            if "no_override" not in name:
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"person_id_{i}_distinct_id_1",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        "$feature_flag": feature_flag.key,
                        feature_flag_property: "test",
                        "$feature_flag_response": "test",
                    },
                )

            # Create the "later" person with email based on test scenario
            if "laterevent" in name and "properties_joined" in name:
                # For JOINED mode with laterevent filter: all users get @otherevent.com to pass filter
                email = f"person_id_{i}@otherevent.com"
            elif "laterevent" in name and "no_override" in name:
                # For NO_OVERRIDE mode with laterevent filter: all 13 users get @otherevent.com to pass filter
                email = f"person_id_{i}@otherevent.com"
            elif "laterevent" in name:
                # For OVERRIDE mode with laterevent filter: only 1 user passes filter
                email = f"person_id_{i}@otherevent.com" if i == 0 else f"person_id_{i}@laterevent.com"
            else:
                # For other tests: use @laterevent.com consistently
                email = f"person_id_{i}@laterevent.com"

            _create_person(
                distinct_ids=[f"person_id_{i}_distinct_id_2"],
                properties={"email": email},
                team_id=self.team.pk,
            )
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"person_id_{i}_distinct_id_2",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    "$feature_flag": feature_flag.key,
                    feature_flag_property: "test",
                    "$feature_flag_response": "test",
                },
            )

            # Create purchase events based on test scenario
            if "laterevent" in name and "properties_joined" in name:
                # For JOINED mode with laterevent filter: first 8 users make purchases (8 successes, 5 failures)
                if i < 8:  # First 8 users make purchases, remaining 5 don't
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"person_id_{i}_distinct_id_2",
                        timestamp="2020-01-02T12:02:00Z",
                        properties={feature_flag_property: "test"},
                    )
            elif "laterevent" in name and "no_override" in name:
                # For NO_OVERRIDE mode with laterevent filter: first 6 users make purchases (6 successes, 7 failures)
                if i < 6:  # First 6 users make purchases, remaining 7 don't
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"person_id_{i}_distinct_id_2",
                        timestamp="2020-01-02T12:02:00Z",
                        properties={feature_flag_property: "test"},
                    )
            elif "laterevent" in name:
                # For OVERRIDE mode with laterevent filter: only first user makes purchase (1 success)
                if i == 0:  # Only user with @otherevent.com makes purchase
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"person_id_{i}_distinct_id_2",
                        timestamp="2020-01-02T12:02:00Z",
                        properties={feature_flag_property: "test"},
                    )
            else:
                # For other tests: first 8 users make purchases (8 success, 5 failure)
                if i < 8:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"person_id_{i}_distinct_id_2",
                        timestamp="2020-01-02T12:02:00Z",
                        properties={feature_flag_property: "test"},
                    )

            # Create the person ID override connection
            create_person_id_override_by_distinct_id(
                f"person_id_{i}_distinct_id_1", f"person_id_{i}_distinct_id_2", self.team.pk
            )

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

            assert result.variant_results is not None
            self.assertEqual(len(result.variant_results), 1)

            control_variant = result.baseline
            assert control_variant is not None
            test_variant = result.variant_results[0]
            assert test_variant is not None

            self.assertEqual(
                {
                    "control_success": int(control_variant.sum),
                    "control_failure": int(control_variant.number_of_samples - control_variant.sum),
                    "test_success": int(test_variant.sum),
                    "test_failure": int(test_variant.number_of_samples - test_variant.sum),
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
            result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_result = result.baseline
        assert control_result is not None
        test_result = result.variant_results[0]
        assert test_result is not None

        self.assertEqual(control_result.sum, 1)  # success_count
        self.assertEqual(test_result.sum, 3)  # success_count
        self.assertEqual(control_result.number_of_samples - control_result.sum, 6)  # failure_count
        self.assertEqual(test_result.number_of_samples - test_result.sum, 6)  # failure_count

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_conversion_window(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data with sufficient sample sizes - tests conversion window functionality
        # Control: 8 successes (within window), 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T13:00:00Z",
                properties={ff_property: "control"},
            )
            if i < 8:  # First 8 users complete funnel within window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-08T11:00:00Z",  # Within conversion window
                    properties={ff_property: "control"},
                )

        # Test: 6 successes (within window), 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T13:00:00Z",
                properties={ff_property: "test"},
            )
            if i < 6:  # First 6 users complete funnel within window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-08T12:30:00Z",  # Within conversion window
                    properties={ff_property: "test"},
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

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=self.team,
        )
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Only events within the conversion window should be counted as successes
        self.assertEqual(control_variant.sum, 8)  # success_count
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # failure_count
        self.assertEqual(test_variant.sum, 6)  # success_count
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # failure_count

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_custom_conversion_window(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        ff_property = f"$feature/{feature_flag.key}"

        # Control group: 8 successful funnels (within window), 5 failures (outside window) - 13 total
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T13:00:00Z",
                properties={ff_property: "control"},
            )
            if i < 8:  # First 8 users complete within 24-hour window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-03T10:00:00Z",  # 21 hours after pageview (within 24h window)
                    properties={ff_property: "control"},
                )
            else:  # Last 5 users purchase outside 24-hour window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-03T14:00:00Z",  # 25 hours after pageview (outside 24h window)
                    properties={ff_property: "control"},
                )

        # Test group: 6 successful funnels (within window), 7 failures (outside window) - 13 total
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T13:00:00Z",
                properties={ff_property: "test"},
            )
            if i < 6:  # First 6 users complete within 24-hour window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-03T10:30:00Z",  # 21.5 hours after pageview (within 24h window)
                    properties={ff_property: "test"},
                )
            else:  # Last 7 users purchase outside 24-hour window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-03T15:00:00Z",  # 26 hours after pageview (outside 24h window)
                    properties={ff_property: "test"},
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
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Only events within the custom conversion window should be counted as successes
        self.assertEqual(control_variant.sum, 8)  # 8 successes within 24h window
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # 5 failures outside window
        self.assertEqual(test_variant.sum, 6)  # 6 successes within 24h window
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # 7 failures outside window

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_action(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        ff_property = f"$feature/{feature_flag.key}"

        # Control group: 8 successful funnels, 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "control"},
            )
            if i < 8:  # First 8 users complete the funnel
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )

        # Test group: 6 successful funnels, 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "test"},
            )
            if i < 6:  # First 6 users complete the funnel
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
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

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 8)  # 8 successful funnels
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # 5 failures
        self.assertEqual(test_variant.sum, 6)  # 6 successful funnels
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # 7 failures

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_duplicate_events(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create test data with sufficient sample sizes for statistics
        # Control group: 8 successful funnels, 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "control"},
            )
            if i < 8:  # First 8 users complete the funnel
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )

        # Test group: 6 successful funnels, 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "test"},
            )
            if i < 6:  # First 6 users complete the funnel
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
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

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=self.team,
        )
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 8)  # 8 successful funnels
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # 5 failures
        self.assertEqual(test_variant.sum, 6)  # 6 successful funnels
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # 7 failures

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_events_out_of_order(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Control group: 8 successful funnels, 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "control"},
            )
            if i < 8:  # First 8 users complete the funnel
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )

        # Test group: 6 successful funnels, 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "test"},
            )
            if i < 6:  # First 6 users complete the funnel
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
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

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=self.team,
        )
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 8)  # 8 successful funnels
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # 5 failures
        self.assertEqual(test_variant.sum, 6)  # 6 successful funnels
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # 7 failures

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_many_steps(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Event sequence for the 6-step funnel
        events = ["$pageview", "add to cart", "checkout started", "checkout completed", "survey submitted", "referral"]

        # Control group: 8 successful funnels, 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Create all 6 steps for successful users (first 8), only partial steps for failures
            steps_to_complete = len(events) if i < 8 else min(3, len(events))  # Failures complete only first 3 steps
            for step_idx, event in enumerate(events[:steps_to_complete]):
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=f"user_control_{i}",
                    timestamp=f"2024-01-02T12:0{step_idx + 1}:00Z",
                    properties={ff_property: "control"},
                )

        # Test group: 6 successful funnels, 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Create all 6 steps for successful users (first 6), only partial steps for failures
            steps_to_complete = len(events) if i < 6 else min(2, len(events))  # Failures complete only first 2 steps
            for step_idx, event in enumerate(events[:steps_to_complete]):
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=f"user_test_{i}",
                    timestamp=f"2024-01-02T12:0{step_idx + 1}:00Z",
                    properties={ff_property: "test"},
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

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=self.team,
        )
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 8)  # 8 successful funnels
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # 5 failures
        self.assertEqual(test_variant.sum, 6)  # 6 successful funnels
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # 7 failures

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_step_property_filter(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Control group: 8 successful funnels, 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            # First step: $pageview with wizard_step=step_1
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "control", "wizard_step": "step_1"},
            )
            if i < 8:  # First 8 users complete the funnel
                # Second step: $pageview with wizard_step=step_2
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control", "wizard_step": "step_2"},
                )

        # Test group: 6 successful funnels, 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            # First step: $pageview with wizard_step=step_1
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "test", "wizard_step": "step_1"},
            )
            if i < 6:  # First 6 users complete the funnel
                # Second step: $pageview with wizard_step=step_2
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test", "wizard_step": "step_2"},
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
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 8)  # 8 successful funnels
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # 5 failures
        self.assertEqual(test_variant.sum, 6)  # 6 successful funnels
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # 7 failures

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_multiple_similar_steps(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Control group: 8 successful funnels, 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            # First step: $pageview
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "control"},
            )
            if i < 8:  # First 8 users complete the full 3-step funnel
                # Second step: first purchase
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )
                # Third step: second purchase
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:03:00Z",
                    properties={ff_property: "control"},
                )
            else:
                # Failures only get first purchase (not second)
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )

        # Test group: 6 successful funnels, 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            # First step: $pageview
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "test"},
            )
            if i < 6:  # First 6 users complete the full 3-step funnel
                # Second step: first purchase
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
                )
                # Third step: second purchase
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:03:00Z",
                    properties={ff_property: "test"},
                )
            else:
                # Failures only get first purchase (not second)
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
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

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=self.team,
        )
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 8)  # 8 successful funnels
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # 5 failures
        self.assertEqual(test_variant.sum, 6)  # 6 successful funnels
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # 7 failures

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_with_unordered_steps(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Control group: 8 successful funnels, 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Create both $pageview and purchase events (order doesn't matter for unordered funnel)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "control"},
            )
            if i < 8:  # First 8 users complete the funnel (have both events)
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )

        # Test group: 6 successful funnels, 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Create both $pageview and purchase events (order doesn't matter for unordered funnel)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={ff_property: "test"},
            )
            if i < 6:  # First 6 users complete the funnel (have both events)
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
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
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 8)  # 8 successful funnels
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)  # 5 failures
        self.assertEqual(test_variant.sum, 6)  # 6 successful funnels
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)  # 7 failures

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_ordered_vs_unordered_comparison(self, name, use_new_query_builder):
        """Test that ordered and unordered funnels behave differently when events are out of order"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Create mixed test data: correct order, reverse order, and incomplete funnels
        # This tests the difference between ordered vs unordered funnels

        # Control group: 6 correct order, 5 reverse order, 2 incomplete (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )

            if i < 6:  # First 6 users: correct order (pageview → purchase)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "control"},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )
            elif i < 11:  # Next 5 users: reverse order (purchase → pageview)
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "control"},
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )
            else:  # Last 2 users: only pageview (incomplete funnel)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "control"},
                )

        # Test group: 5 correct order, 4 reverse order, 4 incomplete (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )

            if i < 5:  # First 5 users: correct order (pageview → purchase)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "test"},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
                )
            elif i < 9:  # Next 4 users: reverse order (purchase → pageview)
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "test"},
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
                )
            else:  # Last 4 users: only pageview (incomplete funnel)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "test"},
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
        ordered_result = query_runner.calculate()

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
        unordered_result = query_runner.calculate()

        # With ordered funnel, the out-of-order events should not be counted as success
        assert ordered_result.variant_results is not None
        self.assertEqual(len(ordered_result.variant_results), 1)
        ordered_control = ordered_result.baseline
        assert ordered_control is not None
        ordered_test = ordered_result.variant_results[0]
        assert ordered_test is not None

        # With unordered funnel, the out-of-order events should be counted as success
        assert unordered_result.variant_results is not None
        self.assertEqual(len(unordered_result.variant_results), 1)
        unordered_control = unordered_result.baseline
        assert unordered_control is not None
        unordered_test = unordered_result.variant_results[0]
        assert unordered_test is not None

        # Ordered funnel: only users with correct order (pageview → purchase) succeed
        self.assertEqual(ordered_control.sum, 6)  # 6 users with correct order
        self.assertEqual(
            ordered_control.number_of_samples - ordered_control.sum, 7
        )  # 7 users with wrong/incomplete order
        self.assertEqual(ordered_test.sum, 5)  # 5 users with correct order
        self.assertEqual(ordered_test.number_of_samples - ordered_test.sum, 8)  # 8 users with wrong/incomplete order

        # Unordered funnel: users with both events succeed regardless of order
        self.assertEqual(unordered_control.sum, 11)  # 6 correct + 5 reverse order (11 with both events)
        self.assertEqual(unordered_control.number_of_samples - unordered_control.sum, 2)  # 2 incomplete (only pageview)
        self.assertEqual(unordered_test.sum, 9)  # 5 correct + 4 reverse order (9 with both events)
        self.assertEqual(unordered_test.number_of_samples - unordered_test.sum, 4)  # 4 incomplete (only pageview)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_excludes_different_feature_flags(self, name, use_new_query_builder):
        """Test that users with $feature_flag_called events for different flags are excluded"""
        # Create two different feature flags
        experiment_flag = self.create_feature_flag(key="experiment-flag")
        other_flag = self.create_feature_flag(key="other-flag")

        experiment = self.create_experiment(feature_flag=experiment_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        experiment_ff_property = f"$feature/{experiment_flag.key}"
        other_ff_property = f"$feature/{other_flag.key}"

        # Control group exposed to experiment flag: 8 successful funnels, 5 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    experiment_ff_property: "control",
                    "$feature_flag": experiment_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={experiment_ff_property: "control"},
            )
            if i < 8:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={experiment_ff_property: "control"},
                )

        # Test group exposed to experiment flag: 6 successful funnels, 7 failures (13 total)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    experiment_ff_property: "test",
                    "$feature_flag": experiment_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={experiment_ff_property: "test"},
            )
            if i < 6:
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={experiment_ff_property: "test"},
                )

        # Users exposed ONLY to other flag (should be excluded from experiment)
        for i in range(10):
            _create_person(distinct_ids=[f"user_other_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_other_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "variant",
                    other_ff_property: "variant",
                    "$feature_flag": other_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_other_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={other_ff_property: "variant"},
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_other_{i}",
                timestamp="2024-01-02T12:02:00Z",
                properties={other_ff_property: "variant"},
            )

        # Users exposed to BOTH flags (should be included in experiment with experiment flag variant)
        for i in range(5):
            _create_person(distinct_ids=[f"user_both_{i}"], team_id=self.team.pk)
            # First see other flag
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_both_{i}",
                timestamp="2024-01-02T11:59:00Z",
                properties={
                    "$feature_flag_response": "variant",
                    other_ff_property: "variant",
                    "$feature_flag": other_flag.key,
                },
            )
            # Then see experiment flag (control)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_both_{i}",
                timestamp="2024-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    experiment_ff_property: "control",
                    "$feature_flag": experiment_flag.key,
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"user_both_{i}",
                timestamp="2024-01-02T12:01:00Z",
                properties={experiment_ff_property: "control"},
            )
            if i < 3:  # 3 of the 5 complete the funnel
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_both_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={experiment_ff_property: "control"},
                )

        flush_persons_and_events()

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

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Control should have: 8 original successes + 3 from both-flags users = 11 successes
        # Control should have: 5 original failures + 2 from both-flags users = 7 failures
        # Total control: 18 exposures (13 + 5 from both-flags users)
        self.assertEqual(control_variant.sum, 11)
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 7)

        # Test should have: 6 successes, 7 failures (13 total)
        self.assertEqual(test_variant.sum, 6)
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)

        # Verify that the 10 users exposed only to other_flag are NOT included
        # Total exposures should be 31 (13 control + 13 test + 5 both), NOT 41 (if other_flag users were included)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_excludes_events_after_experiment_end_date(self, name, use_new_query_builder):
        """Test that funnel metric events after experiment end_date are excluded from results"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 2),
            end_date=datetime(2024, 1, 10),
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Control: 8 users complete within window (success), 5 complete after window (should be failure)
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2024-01-03T12:00:00Z",  # Within experiment window
                properties={
                    "$feature_flag_response": "control",
                    ff_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )

            if i < 8:  # First 8 complete within window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-05T12:00:00Z",  # Within window
                    properties={ff_property: "control"},
                )
            else:  # Last 5 complete after window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-15T12:00:00Z",  # After end_date
                    properties={ff_property: "control"},
                )

        # Test: 6 users complete within window (success), 7 complete after window (should be failure)
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2024-01-03T12:00:00Z",  # Within experiment window
                properties={
                    "$feature_flag_response": "test",
                    ff_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )

            if i < 6:  # First 6 complete within window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-05T12:00:00Z",  # Within window
                    properties={ff_property: "test"},
                )
            else:  # Last 7 complete after window
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-15T12:00:00Z",  # After end_date
                    properties={ff_property: "test"},
                )

        flush_persons_and_events()

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

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Only events within experiment window should count as successes
        self.assertEqual(control_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)
        self.assertEqual(test_variant.sum, 6)
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)

    @parameterized.expand(
        [
            ("disable_new_query_builder_ordered", False, StepOrderValue.ORDERED),
            ("enable_new_query_builder_ordered", True, StepOrderValue.ORDERED),
            ("disable_new_query_builder_unordered", False, StepOrderValue.UNORDERED),
            ("enable_new_query_builder_unordered", True, StepOrderValue.UNORDERED),
        ]
    )
    @freeze_time("2024-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_funnel_metric_events_after_exposure(self, name, use_new_query_builder, funnel_order_type):
        """Test that funnel metric events are only counted if they occur AFTER experiment exposure"""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        # Control group (13 users):
        # - 8 users: events AFTER exposure → SUCCESS
        # - 3 users: events BEFORE exposure → FAILURE (events should be ignored)
        # - 2 users: incomplete funnel after exposure → FAILURE
        for i in range(13):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)

            if i < 8:  # First 8: exposure, then complete funnel (SUCCESS)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:00:00Z",
                    properties={
                        "$feature_flag_response": "control",
                        ff_property: "control",
                        "$feature_flag": feature_flag.key,
                    },
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "control"},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "control"},
                )
            elif i < 11:  # Next 3: complete funnel BEFORE exposure (FAILURE - should be ignored)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T11:58:00Z",  # Before exposure
                    properties={ff_property: "control"},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T11:59:00Z",  # Before exposure
                    properties={ff_property: "control"},
                )
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:00:00Z",
                    properties={
                        "$feature_flag_response": "control",
                        ff_property: "control",
                        "$feature_flag": feature_flag.key,
                    },
                )
            else:  # Last 2: exposure, then incomplete funnel (FAILURE)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:00:00Z",
                    properties={
                        "$feature_flag_response": "control",
                        ff_property: "control",
                        "$feature_flag": feature_flag.key,
                    },
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "control"},
                )
                # No purchase event = incomplete funnel

        # Test group (13 users):
        # - 6 users: events AFTER exposure → SUCCESS
        # - 4 users: events BEFORE exposure → FAILURE (events should be ignored)
        # - 3 users: incomplete funnel after exposure → FAILURE
        for i in range(13):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)

            if i < 6:  # First 6: exposure, then complete funnel (SUCCESS)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:00:00Z",
                    properties={
                        "$feature_flag_response": "test",
                        ff_property: "test",
                        "$feature_flag": feature_flag.key,
                    },
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "test"},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:02:00Z",
                    properties={ff_property: "test"},
                )
            elif i < 10:  # Next 4: complete funnel BEFORE exposure (FAILURE - should be ignored)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T11:58:00Z",  # Before exposure
                    properties={ff_property: "test"},
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T11:59:00Z",  # Before exposure
                    properties={ff_property: "test"},
                )
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:00:00Z",
                    properties={
                        "$feature_flag_response": "test",
                        ff_property: "test",
                        "$feature_flag": feature_flag.key,
                    },
                )
            else:  # Last 3: exposure, then incomplete funnel (FAILURE)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:00:00Z",
                    properties={
                        "$feature_flag_response": "test",
                        ff_property: "test",
                        "$feature_flag": feature_flag.key,
                    },
                )
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_{i}",
                    timestamp="2024-01-02T12:01:00Z",
                    properties={ff_property: "test"},
                )
                # No purchase event = incomplete funnel

        flush_persons_and_events()

        metric = ExperimentFunnelMetric(
            series=[
                EventsNode(event="$pageview"),
                EventsNode(event="purchase"),
            ],
            funnel_order_type=funnel_order_type,
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

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Only events AFTER exposure should count
        # Control: 8 successes (events after exposure), 5 failures (3 before exposure + 2 incomplete)
        self.assertEqual(control_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples - control_variant.sum, 5)

        # Test: 6 successes (events after exposure), 7 failures (4 before exposure + 3 incomplete)
        self.assertEqual(test_variant.sum, 6)
        self.assertEqual(test_variant.number_of_samples - test_variant.sum, 7)
