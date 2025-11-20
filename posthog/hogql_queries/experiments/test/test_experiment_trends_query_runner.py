import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from django.test import override_settings
from django.utils import timezone

from flaky import flaky
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    DataWarehouseNode,
    EventsNode,
    ExperimentSignificanceCode,
    ExperimentTrendsQuery,
    ExperimentTrendsQueryResponse,
    PersonsOnEventsMode,
    PropertyMathType,
    TrendsQuery,
)

from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query

from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql_queries.experiments.experiment_trends_query_runner import ExperimentTrendsQueryRunner
from posthog.hogql_queries.experiments.types import ExperimentMetricType
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.experiment import Experiment, ExperimentHoldout
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.group.util import create_group
from posthog.test.test_journeys import journeys_for
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv

from ee.clickhouse.materialized_columns.columns import get_enabled_materialized_columns, materialize

TEST_BUCKET = "test_storage_bucket-posthog.hogql.datawarehouse.trendquery"


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentTrendsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def teardown_method(self, method) -> None:
        if hasattr(self, "clean_up_data_warehouse_payments_data"):
            self.clean_up_data_warehouse_payments_data()
        if hasattr(self, "clean_up_data_warehouse_usage_data"):
            self.clean_up_data_warehouse_usage_data()
        if hasattr(self, "clean_up_data_warehouse_subscriptions_data"):
            self.clean_up_data_warehouse_subscriptions_data()
        if hasattr(self, "clean_up_data_warehouse_customers_data"):
            self.clean_up_data_warehouse_customers_data()

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

    def create_experiment(
        self,
        name="test-experiment",
        feature_flag=None,
        start_date=None,
        end_date=None,
    ):
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

    def create_holdout_for_experiment(self, experiment: Experiment):
        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Test Experiment holdout",
        )
        holdout.filters = [{"properties": [], "rollout_percentage": 20, "variant": f"holdout-{holdout.id}"}]
        holdout.save()
        experiment.holdout = holdout
        experiment.save()
        return holdout

    def create_data_warehouse_table_with_payments(self):
        table, _, _, _, self.clean_up_data_warehouse_payments_data = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "data" / "payments.csv",
            table_name="payments",
            table_columns={
                "id": "String",
                "dw_timestamp": "DateTime64(3, 'UTC')",
                "dw_distinct_id": "String",
                "amount": "Int64",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=table.name,
            source_table_key="dw_distinct_id",
            joining_table_name="events",
            joining_table_key="distinct_id",
            field_name="events",
            configuration={"experiments_optimized": True, "experiments_timestamp_key": "dw_timestamp"},
        )

        return table.name

    def create_data_warehouse_table_with_usage(self):
        table, _, _, _, self.clean_up_data_warehouse_usage_data = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "data" / "usage.csv",
            table_name="usage",
            table_columns={
                "id": "String",
                "ds": "Date",
                "userid": "String",
                "usage": "Int64",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=table.name,
            source_table_key="userid",
            joining_table_name="events",
            joining_table_key="properties.$user_id",
            field_name="events",
            configuration={"experiments_optimized": True, "experiments_timestamp_key": "ds"},
        )
        return table.name

    def create_data_warehouse_table_with_subscriptions(self):
        subscriptions_table, source, credential, _, self.clean_up_data_warehouse_subscriptions_data = (
            create_data_warehouse_table_from_csv(
                csv_path=Path(__file__).parent / "data" / "subscriptions.csv",
                table_name="subscriptions",
                table_columns={
                    "subscription_id": "String",
                    "subscription_created_at": "DateTime64(3, 'UTC')",
                    "subscription_customer_id": "String",
                    "subscription_amount": "Int64",
                },
                test_bucket=TEST_BUCKET,
                team=self.team,
            )
        )

        customers_table, _, _, _, self.clean_up_data_warehouse_customers_data = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "data" / "customers.csv",
            table_name="customers",
            table_columns={
                "customer_id": "String",
                "customer_created_at": "DateTime64(3, 'UTC')",
                "customer_name": "String",
                "customer_email": "String",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
            credential=credential,
            source=source,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=subscriptions_table.name,
            source_table_key="subscription_customer_id",
            joining_table_name=customers_table.name,
            joining_table_key="customer_id",
            field_name="subscription_customer",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=subscriptions_table.name,
            source_table_key="subscription_customer.customer_email",
            joining_table_name="events",
            joining_table_key="person.properties.email",
            field_name="events",
            configuration={"experiments_optimized": True, "experiments_timestamp_key": "subscription_created_at"},
        )

        return subscriptions_table.name

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate experiment events
        for variant, count in [("control", 11), ("test", 15)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    properties={feature_flag_property: variant},
                )

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in result.variants if variant.key == "control")
        test_result = next(variant for variant in result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 11)
        self.assertEqual(test_result.count, 15)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_custom_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        self.team.test_account_filters = [
            {
                "key": "$host",
                "type": "event",
                "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                "operator": "not_regex",
            },
        ]
        self.team.save()

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")], filterTestAccounts=True)
        exposure_query = TrendsQuery(
            series=[EventsNode(event="custom_exposure_event", properties=[{"key": "valid_exposure", "value": "true"}])],
            filterTestAccounts=True,
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "valid_exposure": "true"},
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "valid_exposure": "true"},
                    },
                ],
                "user_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_out_of_control_exposure": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "false"},
                    },
                ],
                "user_out_of_date_range": [
                    {"event": "$pageview", "timestamp": "2019-01-01", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2019-01-01",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
            },
            self.team,
        )

        # Extraneous internal user exposure event
        _create_event(
            team=self.team,
            event="custom_exposure_event",
            distinct_id="internal_test_1",
            properties={
                "valid_exposure": "true",
                ff_property: "test",
                "$host": "localhost",
            },
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 2)

        # Run again with filterTestAccounts=False
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")], filterTestAccounts=False)
        exposure_query = TrendsQuery(
            series=[EventsNode(event="custom_exposure_event", properties=[{"key": "valid_exposure", "value": "true"}])],
            filterTestAccounts=False,
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 3)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_custom_exposure_sum_math(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview", math="sum", math_property="amount")])
        exposure_query = TrendsQuery(
            series=[EventsNode(event="custom_exposure_event", properties=[{"key": "valid_exposure", "value": "true"}])]
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "amount": 100},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "amount": 200},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
                "user_control_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "amount": 100},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
                "user_test_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "amount": 100},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "amount": 200},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "amount": 300},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "valid_exposure": "true"},
                    },
                ],
                "user_test_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "amount": 100},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "amount": 200},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "valid_exposure": "true"},
                    },
                ],
                "user_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"amount": 100}},
                ],
                "user_out_of_control_exposure": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "false"},
                    },
                ],
                "user_out_of_date_range": [
                    {
                        "event": "$pageview",
                        "timestamp": "2019-01-01",
                        "properties": {ff_property: "control", "amount": 100},
                    },
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2019-01-01",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 400)
        self.assertEqual(test_result.count, 900)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_default_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,  # No exposure query provided
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "test", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "test", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_out_of_control_exposure": [
                    {"event": "$feature_flag_called", "timestamp": "2020-01-02"},
                ],
                "user_out_of_date_range": [
                    {"event": "$pageview", "timestamp": "2019-01-01", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2019-01-01",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_action(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        action = Action.objects.create(name="pageview", team=self.team, steps_json=[{"event": "$pageview"}])
        action.save()

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[ActionsNode(id=action.id)])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,  # No exposure query provided
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "test", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "test", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_out_of_control_exposure": [
                    {"event": "$feature_flag_called", "timestamp": "2020-01-02"},
                ],
                "user_out_of_date_range": [
                    {"event": "$pageview", "timestamp": "2019-01-01", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2019-01-01",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_holdout(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        holdout = self.create_holdout_for_experiment(experiment)

        feature_flag_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate experiment events
        for variant, count in [("control", 11), ("test", 15), (f"holdout-{holdout.id}", 8)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    properties={feature_flag_property: variant},
                )

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9), (f"holdout-{holdout.id}", 4)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 3)

        control_result = next(variant for variant in result.variants if variant.key == "control")
        test_result = next(variant for variant in result.variants if variant.key == "test")
        holdout_result = next(variant for variant in result.variants if variant.key == f"holdout-{holdout.id}")

        self.assertEqual(control_result.count, 11)
        self.assertEqual(test_result.count, 15)
        self.assertEqual(holdout_result.count, 8)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)
        self.assertEqual(holdout_result.absolute_exposure, 4)

    @parameterized.expand(
        [
            [
                "person_properties",
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "control_absolute_exposure": 12,
                    "test_absolute_exposure": 15,
                },
            ],
            [
                "event_properties",
                {
                    "key": "$host",
                    "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                    "operator": "not_regex",
                    "type": "event",
                },
                {
                    "control_absolute_exposure": 6,
                    "test_absolute_exposure": 6,
                },
            ],
            [
                "feature_flags",
                {
                    "key": "$feature/flag_doesnt_exist",
                    "type": "event",
                    "value": ["test", "control"],
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 0,
                    "test_absolute_exposure": 0,
                },
            ],
            [
                "cohort_static",
                {
                    "key": "id",
                    "type": "static-cohort",
                    # value is generated in the test
                    "value": None,
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 2,
                    "test_absolute_exposure": 1,
                },
            ],
            [
                "cohort_dynamic",
                {
                    "key": "id",
                    "type": "cohort",
                    # value is generated in the test
                    "value": None,
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 2,
                    "test_absolute_exposure": 1,
                },
            ],
            [
                "group",
                {
                    "key": "name",
                    "type": "group",
                    # Value is generated in the test
                    "value": None,
                    "operator": "exact",
                    "group_type_index": 0,
                },
                {
                    "control_absolute_exposure": 8,
                    "test_absolute_exposure": 10,
                },
            ],
            [
                "element",
                {
                    "key": "tag_name",
                    "type": "element",
                    "value": ["button"],
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 0,
                    "test_absolute_exposure": 0,
                },
            ],
        ]
    )
    def test_query_runner_with_internal_filters(self, name: str, filter: dict, expected_results: dict):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        cohort = None
        if name == "cohort_static":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_static",
                is_static=True,
            )
            filter["value"] = cohort.pk
        elif name == "cohort_dynamic":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_dynamic",
                groups=[
                    {
                        "properties": [
                            {"key": "email", "operator": "not_icontains", "value": "@posthog.com", "type": "person"},
                        ]
                    }
                ],
            )
            filter["value"] = cohort.pk
        elif name == "group":
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
            )
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="my_awesome_group",
                properties={"name": "Test Group"},
            )
            filter["value"] = ["Test Group"]

        self.team.test_account_filters = [filter]
        self.team.save()

        feature_flag_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")], filterTestAccounts=True)

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate count events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                extra_properties = {"$host": "localhost", "$group_0": "my_awesome_group"} if i > 5 else {}
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    properties={feature_flag_property: variant, **extra_properties},
                )

        # Populate exposure events
        for variant, count in [("control", 14), ("test", 16)]:
            for i in range(count):
                extra_properties = {"$host": "localhost", "$group_0": "my_awesome_group"} if i > 5 else {}
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                        **extra_properties,
                    },
                )

        _create_person(
            team=self.team,
            distinct_ids=["user_control_1"],
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_control_2"],
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_control_3"],
            properties={"email": "user_control_3@posthog.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_control_6"],
            properties={"email": "user_control_6@posthog.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_test_2"],
            properties={"email": "user_test_2@posthog.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_test_3"],
        )

        flush_persons_and_events()

        if name == "cohort_static" and cohort:
            cohort.insert_users_by_list(["user_control_1", "user_control_2", "user_test_2"])
            self.assertEqual(cohort.people.count(), 3)
        elif name == "cohort_dynamic" and cohort:
            cohort.calculate_people_ch(pending_version=0)

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        # "feature_flags" and "element" filter out all events
        if name == "feature_flags" or name == "element":
            with self.assertRaises(ValidationError) as context:
                query_runner.calculate()

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
            trend_result = cast(ExperimentTrendsQueryResponse, result)

            control_result = next(variant for variant in trend_result.variants if variant.key == "control")
            test_result = next(variant for variant in trend_result.variants if variant.key == "test")

            self.assertEqual(control_result.absolute_exposure, expected_results["control_absolute_exposure"])
            self.assertEqual(test_result.absolute_exposure, expected_results["test_absolute_exposure"])

        ## Run again with filterTestAccounts=False
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")], filterTestAccounts=False)
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.absolute_exposure, 14)
        self.assertEqual(test_result.absolute_exposure, 16)

    def test_query_runner_with_data_warehouse_series_total_count(self):
        table_name = self.create_data_warehouse_table_with_payments()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="dw_distinct_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="dw_timestamp",
                    math="total",
                )
            ]
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        # "user_test_3" first exposure (feature_flag_property="control") is on 2023-01-03
        # "user_test_3" relevant exposure (feature_flag_property="test") is on 2023-01-04
        # "user_test_3" other event (feature_flag_property="control" is on 2023-01-05
        # "user_test_3" purchase is on 2023-01-06
        # "user_test_3" second exposure (feature_flag_property="control") is on 2023-01-09
        # "user_test_3" should fall into the "test" variant, not the "control" variant
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test_3",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 3),
        )
        _create_event(
            team=self.team,
            event="Some other event",
            distinct_id="user_test_3",
            properties={feature_flag_property: "control"},
            timestamp=datetime(2023, 1, 5),
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test_3",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 9),
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)
        self.assertEqual(control_result.absolute_exposure, 9)
        self.assertEqual(test_result.absolute_exposure, 9)

    def test_query_runner_with_data_warehouse_series_avg_amount(self):
        table_name = self.create_data_warehouse_table_with_payments()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="dw_distinct_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="dw_timestamp",
                    math="avg",
                    math_property="amount",
                    math_property_type="data_warehouse_properties",
                )
            ]
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        # "user_test_3" first exposure (feature_flag_property="control") is on 2023-01-03
        # "user_test_3" relevant exposure (feature_flag_property="test") is on 2023-01-04
        # "user_test_3" other event (feature_flag_property="control" is on 2023-01-05
        # "user_test_3" purchase is on 2023-01-06
        # "user_test_3" second exposure (feature_flag_property="control") is on 2023-01-09
        # "user_test_3" should fall into the "test" variant, not the "control" variant
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 3),
        )
        _create_event(
            team=self.team,
            event="Some other event",
            distinct_id="user_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 5),
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 9),
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 100)
        self.assertEqual(test_result.count, 205)
        self.assertEqual(control_result.absolute_exposure, 9)
        self.assertEqual(test_result.absolute_exposure, 9)

        self.assertEqual(
            control_insight["data"],
            [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        )
        self.assertEqual(
            test_insight["data"],
            [0.0, 50.0, 125.0, 125.0, 125.0, 205.0, 205.0, 205.0, 205.0, 205.0],
        )

    @parameterized.expand(
        [
            [
                "person_properties",
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "control_absolute_exposure": 8,
                    "test_absolute_exposure": 9,
                },
            ],
            [
                "event_properties",
                {
                    "key": "$host",
                    "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                    "operator": "not_regex",
                    "type": "event",
                },
                {
                    "control_absolute_exposure": 8,
                    "test_absolute_exposure": 9,
                },
            ],
            [
                "feature_flags",
                {
                    "key": "$feature/flag_doesnt_exist",
                    "type": "event",
                    "value": ["test", "control"],
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 0,
                    "test_absolute_exposure": 0,
                },
            ],
            [
                "cohort_static",
                {
                    "key": "id",
                    "type": "cohort",
                    # value is generated in the test
                    "value": None,
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 1,
                    "test_absolute_exposure": 1,
                },
            ],
            [
                "cohort_dynamic",
                {
                    "key": "id",
                    "type": "cohort",
                    # value is generated in the test
                    "value": None,
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 2,
                    "test_absolute_exposure": 1,
                },
            ],
            [
                "group",
                {
                    "key": "name",
                    "type": "group",
                    # Value is generated in the test
                    "value": None,
                    "operator": "exact",
                    "group_type_index": 0,
                },
                {
                    "control_absolute_exposure": 7,
                    "test_absolute_exposure": 9,
                },
            ],
            [
                "element",
                {
                    "key": "tag_name",
                    "type": "element",
                    "value": ["button"],
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 0,
                    "test_absolute_exposure": 0,
                },
            ],
        ]
    )
    def test_query_runner_with_data_warehouse_internal_filters(self, name, filter: dict, filter_expected: dict):
        table_name = self.create_data_warehouse_table_with_usage()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        cohort = None
        if name == "cohort_static":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_static",
                is_static=True,
            )
            filter["value"] = cohort.pk
        elif name == "cohort_dynamic":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_dynamic",
                groups=[
                    {
                        "properties": [
                            {"key": "email", "operator": "not_icontains", "value": "@posthog.com", "type": "person"}
                        ]
                    }
                ],
            )
            filter["value"] = cohort.pk
        elif name == "group":
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
            )
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="my_awesome_group",
                properties={"name": "Test Group"},
            )
            filter["value"] = ["Test Group"]

        self.team.test_account_filters = [filter]
        self.team.save()
        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="userid",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="ds",
                    math="avg",
                    math_property="usage",
                    math_property_type="data_warehouse_properties",
                )
            ],
            filterTestAccounts=True,
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")], filterTestAccounts=True)

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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

        _create_person(
            team=self.team,
            distinct_ids=["distinct_control_0"],
        )

        _create_person(
            team=self.team,
            distinct_ids=["distinct_test_3"],
        )

        _create_person(
            team=self.team,
            distinct_ids=["internal_test_1"],
            properties={"email": "internal_test_1@posthog.com"},
        )
        # 10th exposure for 'test'
        # filtered out by "event_properties" , "person_properties", and "group"
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="internal_test_1",
            properties={
                feature_flag_property: "test",
                "$feature_flag_response": "test",
                "$feature_flag": feature_flag.key,
                "$user_id": "internal_test_1",
                "$host": "127.0.0.1",
            },
            timestamp=datetime(2023, 1, 3),
        )

        # "user_test_3" first exposure (feature_flag_property="control") is on 2023-01-03
        # "user_test_3" relevant exposure (feature_flag_property="test") is on 2023-01-04
        # "user_test_3" other event (feature_flag_property="control" is on 2023-01-05
        # "user_test_3" purchase is on 2023-01-06
        # "user_test_3" second exposure (feature_flag_property="control") is on 2023-01-09
        # "user_test_3" should fall into the "test" variant, not the "control" variant
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 3),
        )
        _create_event(
            team=self.team,
            event="Some other event",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 5),
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 9),
        )

        flush_persons_and_events()

        if name == "cohort_static" and cohort:
            cohort.insert_users_by_list(["distinct_control_0", "internal_test_1"])
            self.assertEqual(cohort.people.count(), 2)
        elif name == "cohort_dynamic" and cohort:
            cohort.calculate_people_ch(pending_version=0)

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        # "feature_flags" and "element" filter out all events
        if name == "feature_flags" or name == "element":
            with freeze_time("2023-01-07"), self.assertRaises(ValidationError) as context:
                query_runner.calculate()

            expected_errors = json.dumps(
                {
                    ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
                    ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                    ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
                }
            )
            self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)
        else:
            with freeze_time("2023-01-07"):
                result = query_runner.calculate()

            trend_result = cast(ExperimentTrendsQueryResponse, result)

            self.assertEqual(len(result.variants), 2)

            control_result = next(variant for variant in trend_result.variants if variant.key == "control")
            test_result = next(variant for variant in trend_result.variants if variant.key == "test")

            self.assertEqual(control_result.absolute_exposure, filter_expected["control_absolute_exposure"])
            self.assertEqual(test_result.absolute_exposure, filter_expected["test_absolute_exposure"])

        # Run the query again without filtering
        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="userid",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="ds",
                    math="avg",
                    math_property="usage",
                    math_property_type="data_warehouse_properties",
                )
            ],
            filterTestAccounts=False,
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")], filterTestAccounts=False)

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.absolute_exposure, 8)
        self.assertEqual(test_result.absolute_exposure, 10)

    def test_query_runner_with_data_warehouse_series_no_end_date_and_nested_id(self):
        table_name = self.create_data_warehouse_table_with_usage()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            },
            {
                "key": "$host",
                "type": "event",
                "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                "operator": "not_regex",
            },
        ]
        self.team.save()
        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="userid",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="ds",
                    math="avg",
                    math_property="usage",
                    math_property_type="data_warehouse_properties",
                )
            ],
            filterTestAccounts=True,
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        _create_person(
            team=self.team,
            uuid="018f14b8-6cf3-7ffd-80bb-5ef1a9e4d328",
            distinct_ids=["018f14b8-6cf3-7ffd-80bb-5ef1a9e4d328", "internal_test_1"],
            properties={"email": "internal_test_1@posthog.com"},
        )

        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="internal_test_1",
            properties={
                feature_flag_property: "test",
                "$feature_flag_response": "test",
                "$feature_flag": feature_flag.key,
                "$user_id": "internal_test_1",
            },
            timestamp=datetime(2023, 1, 3),
        )

        # "user_test_3" first exposure (feature_flag_property="control") is on 2023-01-03
        # "user_test_3" relevant exposure (feature_flag_property="test") is on 2023-01-04
        # "user_test_3" other event (feature_flag_property="control" is on 2023-01-05
        # "user_test_3" purchase is on 2023-01-06
        # "user_test_3" second exposure (feature_flag_property="control") is on 2023-01-09
        # "user_test_3" should fall into the "test" variant, not the "control" variant
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 3),
        )
        _create_event(
            team=self.team,
            event="Some other event",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 5),
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 9),
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            # Build and execute the query to get the ClickHouse SQL
            queries = query_runner.count_query_runner.to_queries()
            response = execute_hogql_query(
                query_type="TrendsQuery",
                query=queries[0],
                team=query_runner.count_query_runner.team,
                modifiers=query_runner.count_query_runner.modifiers,
                limit_context=query_runner.count_query_runner.limit_context,
            )

            # Assert the expected join condition in the clickhouse SQL
            expected_join_condition = f"and(equals(events.team_id, {query_runner.count_query_runner.team.id}), equals(event, %(hogql_val_9)s), greaterOrEquals(timestamp, assumeNotNull(toDateTime(%(hogql_val_10)s, %(hogql_val_11)s))), lessOrEquals(timestamp, assumeNotNull(toDateTime(%(hogql_val_12)s, %(hogql_val_13)s))))) AS e__events ON"
            self.assertIn(
                expected_join_condition,
                str(response.clickhouse),
                "Please check to make sure the timestamp statements are included in the ASOF LEFT JOIN select statement. This may also fail if the placeholder numbers have changed.",
            )

            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 1000)
        self.assertEqual(test_result.count, 2050)
        self.assertEqual(control_result.absolute_exposure, 9)
        self.assertEqual(test_result.absolute_exposure, 9)

        self.assertEqual(
            control_insight["data"][:10],
            [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        )
        self.assertEqual(
            test_insight["data"][:10],
            [0.0, 500.0, 1250.0, 1250.0, 1250.0, 2050.0, 2050.0, 2050.0, 2050.0, 2050.0],
        )

        # Run the query again with filter_test_accounts=False
        # as a point of comparison to above
        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="userid",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="ds",
                    math="avg",
                    math_property="usage",
                    math_property_type="data_warehouse_properties",
                )
            ],
            filterTestAccounts=False,
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")], filterTestAccounts=False)

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 1000)
        self.assertEqual(test_result.count, 102050)
        self.assertEqual(control_result.absolute_exposure, 9)
        self.assertEqual(test_result.absolute_exposure, 10)

        self.assertEqual(
            control_insight["data"][:10],
            [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        )
        self.assertEqual(
            test_insight["data"][:10],
            [0.0, 500.0, 1250.0, 101250.0, 101250.0, 102050.0, 102050.0, 102050.0, 102050.0, 102050.0],
        )

    def test_query_runner_with_data_warehouse_series_internal_user_filter(self):
        table_name = self.create_data_warehouse_table_with_usage()
        materialize("person", "email")
        materialize("events", "email", table_column="person_properties")

        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS}
        self.team.save()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"
        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            },
            {
                "key": "$host",
                "type": "event",
                "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                "operator": "not_regex",
            },
        ]
        self.team.save()
        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="userid",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="ds",
                    math="avg",
                    math_property="usage",
                    math_property_type="data_warehouse_properties",
                )
            ],
            filterTestAccounts=True,
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        _create_person(
            team=self.team,
            uuid="018f14b8-6cf3-7ffd-80bb-5ef1a9e4d328",
            distinct_ids=["018f14b8-6cf3-7ffd-80bb-5ef1a9e4d328", "internal_test_1"],
            properties={"email": "internal_test_1@posthog.com"},
        )

        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="internal_test_1",
            properties={
                feature_flag_property: "test",
                "$feature_flag_response": "test",
                "$feature_flag": feature_flag.key,
                "$user_id": "internal_test_1",
            },
            timestamp=datetime(2023, 1, 3),
        )

        # "user_test_3" first exposure (feature_flag_property="control") is on 2023-01-03
        # "user_test_3" relevant exposure (feature_flag_property="test") is on 2023-01-04
        # "user_test_3" other event (feature_flag_property="control" is on 2023-01-05
        # "user_test_3" purchase is on 2023-01-06
        # "user_test_3" second exposure (feature_flag_property="control") is on 2023-01-09
        # "user_test_3" should fall into the "test" variant, not the "control" variant
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 3),
        )
        _create_event(
            team=self.team,
            event="Some other event",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 5),
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 9),
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            # Build and execute the query to get the ClickHouse SQL
            queries = query_runner.count_query_runner.to_queries()
            response = execute_hogql_query(
                query_type="TrendsQuery",
                query=queries[0],
                team=query_runner.count_query_runner.team,
                modifiers=query_runner.count_query_runner.modifiers,
                limit_context=query_runner.count_query_runner.limit_context,
            )

            materialized_columns = get_enabled_materialized_columns("events")
            self.assertIn("mat_pp_email", [col.name for col in materialized_columns.values()])
            # Assert the expected email where statement in the clickhouse SQL
            expected_email_where_statement = "notILike(toString(e__events.poe___properties___email), %(hogql_val_25)s"
            self.assertIn(
                expected_email_where_statement,
                str(response.clickhouse),
            )

            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 1000)
        self.assertEqual(test_result.count, 2050)
        self.assertEqual(control_result.absolute_exposure, 9)
        self.assertEqual(test_result.absolute_exposure, 9)

        self.assertEqual(
            control_insight["data"][:10],
            [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        )
        self.assertEqual(
            test_insight["data"][:10],
            [0.0, 500.0, 1250.0, 1250.0, 1250.0, 2050.0, 2050.0, 2050.0, 2050.0, 2050.0],
        )

        # Run the query again with filter_test_accounts=False
        # as a point of comparison to above
        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="userid",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="ds",
                    math="avg",
                    math_property="usage",
                    math_property_type="data_warehouse_properties",
                )
            ],
            filterTestAccounts=False,
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")], filterTestAccounts=False)

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 1000)
        self.assertEqual(test_result.count, 102050)
        self.assertEqual(control_result.absolute_exposure, 9)
        self.assertEqual(test_result.absolute_exposure, 10)

        self.assertEqual(
            control_insight["data"][:10],
            [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        )
        self.assertEqual(
            test_insight["data"][:10],
            [0.0, 500.0, 1250.0, 101250.0, 101250.0, 102050.0, 102050.0, 102050.0, 102050.0, 102050.0],
        )

    def test_query_runner_with_data_warehouse_series_expected_query(self):
        table_name = self.create_data_warehouse_table_with_payments()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="dw_distinct_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="dw_timestamp",
                    math="total",
                )
            ]
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            # Build and execute the query to get the ClickHouse SQL
            queries = query_runner.count_query_runner.to_queries()
            response = execute_hogql_query(
                query_type="TrendsQuery",
                query=queries[0],
                team=query_runner.count_query_runner.team,
                modifiers=query_runner.count_query_runner.modifiers,
                limit_context=query_runner.count_query_runner.limit_context,
            )

            # Assert the expected join condition in the clickhouse SQL
            expected_join_condition = f"and(equals(events.team_id, {query_runner.count_query_runner.team.id}), equals(event, %(hogql_val_7)s), greaterOrEquals(timestamp, assumeNotNull(toDateTime(%(hogql_val_8)s, %(hogql_val_9)s))), lessOrEquals(timestamp, assumeNotNull(toDateTime(%(hogql_val_10)s, %(hogql_val_11)s))))) AS e__events ON"
            self.assertIn(
                expected_join_condition,
                str(response.clickhouse),
                "Please check to make sure the timestamp statements are included in the ASOF LEFT JOIN select statement. This may also fail if the placeholder numbers have changed.",
            )

            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    def test_query_runner_with_data_warehouse_subscriptions_table(self):
        table_name = self.create_data_warehouse_table_with_subscriptions()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="subscription_customer_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="subscription_created_at",
                    math="total",
                )
            ]
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        _create_person(
            team=self.team,
            distinct_ids=["user_control_0"],
            properties={"email": "john.doe@example.com"},
        )

        _create_person(
            team=self.team,
            distinct_ids=["user_test_1"],
            properties={"email": "jane.doe@example.com"},
        )

        _create_person(
            team=self.team,
            distinct_ids=["user_test_2"],
            properties={"email": "john.smith@example.com"},
        )

        _create_person(
            team=self.team,
            distinct_ids=["user_test_3"],
            properties={"email": "jane.smith@example.com"},
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )

        with freeze_time("2023-01-10"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    def test_query_runner_with_invalid_data_warehouse_table_name(self):
        # parquet file isn't created, so we'll get an error
        table_name = "invalid_table_name"

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="dw_distinct_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="dw_timestamp",
                )
            ]
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            with self.assertRaises(QueryError) as context:
                query_runner.calculate()

        assert "invalid_table_name" in str(context.exception)

    # Uses the same values as test_query_runner_with_data_warehouse_series_avg_amount for easy comparison
    @freeze_time("2020-01-01T00:00:00Z")
    def test_query_runner_with_avg_math_v2_stats(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                EventsNode(event="purchase", math="sum", math_property="amount", math_property_type="event_properties")
            ],
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )

        # Populate exposure events - same as data warehouse test
        for variant, count in [("control", 1), ("test", 3)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                    timestamp=datetime(2020, 1, i + 1),
                )

        # Create purchase events with same amounts as data warehouse test
        # Control: 1 purchase of 100
        # Test: 3 purchases of 50, 75, and 80
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_control_0",
            properties={feature_flag_property: "control", "amount": 100},
            timestamp=datetime(2020, 1, 2),
        )

        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_1",
            properties={feature_flag_property: "test", "amount": 50},
            timestamp=datetime(2020, 1, 2),
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_2",
            properties={feature_flag_property: "test", "amount": 75},
            timestamp=datetime(2020, 1, 3),
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_3",
            properties={feature_flag_property: "test", "amount": 80},
            timestamp=datetime(2020, 1, 6),
        )

        flush_persons_and_events()

        prepared_count_query = query_runner.prepared_count_query
        self.assertEqual(prepared_count_query.series[0].math, "sum")

        result = query_runner.calculate()
        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(trend_result.significant, False)
        self.assertEqual(trend_result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertEqual(trend_result.p_value, 1.0)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 100)
        self.assertAlmostEqual(test_result.count, 205)
        self.assertEqual(control_result.absolute_exposure, 1)
        self.assertEqual(test_result.absolute_exposure, 3)

        self.assertEqual(
            control_insight["data"],
            [0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        )
        self.assertEqual(
            test_insight["data"],
            [0.0, 50.0, 125.0, 125.0, 125.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0],
        )

    @flaky(max_runs=10, min_passes=1)
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_standard_flow_v2_stats(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
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

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)
        for variant in result.variants:
            self.assertIn(variant.key, ["control", "test"])

        control_variant = next(v for v in result.variants if v.key == "control")
        test_variant = next(v for v in result.variants if v.key == "test")

        self.assertEqual(control_variant.count, 3)
        self.assertEqual(test_variant.count, 5)
        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 2)

        self.assertAlmostEqual(result.credible_intervals["control"][0], 0.3633, delta=0.1)
        self.assertAlmostEqual(result.credible_intervals["control"][1], 2.9224, delta=0.1)
        self.assertAlmostEqual(result.credible_intervals["test"][0], 0.7339, delta=0.1)
        self.assertAlmostEqual(result.credible_intervals["test"][1], 3.8894, delta=0.1)

        self.assertAlmostEqual(result.p_value, 1.0, delta=0.1)

        self.assertAlmostEqual(result.probability["control"], 0.2549, delta=0.1)
        self.assertAlmostEqual(result.probability["test"], 0.7453, delta=0.1)

        self.assertEqual(result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)

        self.assertFalse(result.significant)

        self.assertEqual(len(result.variants), 2)

        self.assertEqual(control_variant.absolute_exposure, 2.0)
        self.assertEqual(control_variant.count, 3.0)
        self.assertEqual(control_variant.exposure, 1.0)

        self.assertEqual(test_variant.absolute_exposure, 2.0)
        self.assertEqual(test_variant.count, 5.0)
        self.assertEqual(test_variant.exposure, 1.0)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_control(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        journeys_for(
            {
                "user_test": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: False,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_test(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        journeys_for(
            {
                "user_control": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EXPOSURES: False,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: False,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"

        journeys_for(
            {
                "user_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                ],
                "user_test": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: False,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: False,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    def test_get_metric_type(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        # Test allowed count math types
        allowed_count_math_types = [BaseMathType.TOTAL, BaseMathType.DAU, BaseMathType.UNIQUE_SESSION, None]
        for math_type in allowed_count_math_types:
            count_query = TrendsQuery(series=[EventsNode(event="$pageview", math=math_type)])
            experiment_query = ExperimentTrendsQuery(
                experiment_id=experiment.id,
                kind="ExperimentTrendsQuery",
                count_query=count_query,
            )
            query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
            self.assertEqual(query_runner._get_metric_type(), ExperimentMetricType.COUNT)

        # Test allowed sum math types
        allowed_sum_math_types: list[Any] = [PropertyMathType.SUM, "hogql"]
        for math_type in allowed_sum_math_types:
            count_query = TrendsQuery(
                series=[EventsNode(event="checkout completed", math=math_type, math_property="revenue")]
            )
            experiment_query = ExperimentTrendsQuery(
                experiment_id=experiment.id,
                kind="ExperimentTrendsQuery",
                count_query=count_query,
            )
            query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
            self.assertEqual(query_runner._get_metric_type(), ExperimentMetricType.CONTINUOUS)

        # Test that AVG math gets converted to SUM and returns CONTINUOUS
        count_query = TrendsQuery(
            series=[EventsNode(event="checkout completed", math=PropertyMathType.AVG, math_property="revenue")]
        )
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )
        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        self.assertEqual(query_runner._get_metric_type(), ExperimentMetricType.CONTINUOUS)
        # Verify the math type was converted to sum
        self.assertEqual(query_runner.query.count_query.series[0].math, PropertyMathType.SUM)
