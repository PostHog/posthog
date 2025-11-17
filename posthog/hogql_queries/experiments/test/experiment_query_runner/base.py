from datetime import timedelta
from pathlib import Path

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from django.test import override_settings
from django.utils import timezone

from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag

from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.hogql.experiments.queryrunner"


@override_settings(IN_UNIT_TESTING=True)
class ExperimentQueryRunnerBaseTest(ClickhouseTestMixin, APIBaseTest):
    def teardown_method(self, method) -> None:
        if getattr(self, "clean_up_data_warehouse_usage_data", None):
            self.clean_up_data_warehouse_usage_data()
        if getattr(self, "clean_up_data_warehouse_subscriptions_data", None):
            self.clean_up_data_warehouse_subscriptions_data()
        if getattr(self, "clean_up_data_warehouse_customers_data", None):
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
            exposure_criteria=None,
        )

    def create_data_warehouse_table_with_usage(self):
        table, _, _, _, self.clean_up_data_warehouse_usage_data = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "data" / "usage.csv",
            table_name="usage",
            table_columns={
                "id": "String",
                "ds": "Date",
                "userid": "String",
                "usage": "Float64",
                "plan": "String",
                "region": "String",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        return table.name

    def create_data_warehouse_table_with_subscriptions(self):
        subscription_table_name = "stripe_subscriptions"
        subscriptions_table, source, credential, _, self.clean_up_data_warehouse_subscriptions_data = (
            create_data_warehouse_table_from_csv(
                csv_path=Path(__file__).parent / "data" / "subscriptions.csv",
                table_name=subscription_table_name,
                table_columns={
                    "subscription_id": "String",
                    "subscription_created_at": "DateTime",
                    "subscription_customer_id": "String",
                    "subscription_amount": "Int64",
                },
                test_bucket=TEST_BUCKET,
                team=self.team,
            )
        )

        customer_table_name = "stripe_customers"
        customers_table, _, _, _, self.clean_up_data_warehouse_customers_data = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "data" / "customers.csv",
            table_name=customer_table_name,
            table_columns={
                "customer_id": "String",
                "customer_created_at": "DateTime",
                "customer_name": "String",
                "customer_email": "String",
                "signup_count": "Int32",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
            source=source,
            credential=credential,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=subscriptions_table.name,
            source_table_key="subscription_customer_id",
            joining_table_name=customers_table.name,
            joining_table_key="customer_id",
            field_name="subscription_customer",
        )

        return subscriptions_table.name

    def create_standard_test_events(self, feature_flag):
        """
        Creates a standard set of events that can be reused across multiple tests
        """

        feature_flag_property = f"$feature/{feature_flag.key}"

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant, "amount": 10 if i < 2 else ""},
                    )
