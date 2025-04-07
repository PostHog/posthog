from django.test import override_settings
from posthog.hogql_queries.experiments.test.experiment_query_runner.utils import (
    create_data_warehouse_table,
)
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    XDIST_SUFFIX,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)
from django.utils import timezone
from datetime import datetime, timedelta
from posthog.models.experiment import Experiment
from boto3 import resource
from botocore.config import Config
from posthog.warehouse.models.join import DataWarehouseJoin

TEST_BUCKET = "test_storage_bucket-posthog.hogql.experiments.queryrunner" + XDIST_SUFFIX


@override_settings(IN_UNIT_TESTING=True)
class ExperimentQueryRunnerBaseTest(ClickhouseTestMixin, APIBaseTest):
    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

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
        table_data = [
            {"id": "1", "ds": "2023-01-01", "userid": "user_control_0", "usage": "1000"},
            {"id": "2", "ds": "2023-01-02", "userid": "user_test_1", "usage": "500"},
            {"id": "3", "ds": "2023-01-03", "userid": "user_test_2", "usage": "750"},
            {"id": "4", "ds": "2023-01-04", "userid": "internal_test_1", "usage": "100000"},
            {"id": "5", "ds": "2023-01-06", "userid": "user_test_3", "usage": "800"},
            {"id": "6", "ds": "2023-01-07", "userid": "user_extra", "usage": "900"},
        ]

        columns = {
            "id": "String",
            "ds": "Date",
            "userid": "String",
            "usage": "String",
        }

        table_name = "usage"

        create_data_warehouse_table(self.team, table_name, table_data, columns)

        return table_name

    def create_data_warehouse_table_with_subscriptions(self):
        subscription_table_name = "subscriptions"
        subscription_columns = {
            "subscription_id": "String",
            "subscription_created_at": "DateTime64(3, 'UTC')",
            "subscription_customer_id": "String",
            "subscription_amount": "Int64",
        }
        subscription_table_data = [
            {
                "subscription_id": "1",
                "subscription_created_at": datetime(2023, 1, 2),
                "subscription_customer_id": "1",
                "subscription_amount": 100,
            },
            {
                "subscription_id": "2",
                "subscription_created_at": datetime(2023, 1, 3),
                "subscription_customer_id": "2",
                "subscription_amount": 50,
            },
            {
                "subscription_id": "3",
                "subscription_created_at": datetime(2023, 1, 4),
                "subscription_customer_id": "3",
                "subscription_amount": 75,
            },
            {
                "subscription_id": "4",
                "subscription_created_at": datetime(2023, 1, 5),
                "subscription_customer_id": "4",
                "subscription_amount": 80,
            },
            {
                "subscription_id": "5",
                "subscription_created_at": datetime(2023, 1, 6),
                "subscription_customer_id": "5",
                "subscription_amount": 90,
            },
        ]
        create_data_warehouse_table(self.team, subscription_table_name, subscription_table_data, subscription_columns)

        customer_table_name = "customers"
        customer_columns = {
            "customer_id": "String",
            "customer_created_at": "DateTime64(3, 'UTC')",
            "customer_name": "String",
            "customer_email": "String",
        }
        customer_table_data = [
            {
                "customer_id": "1",
                "customer_created_at": datetime(2023, 1, 1),
                "customer_name": "John Doe",
                "customer_email": "john.doe@example.com",
            },
            {
                "customer_id": "2",
                "customer_created_at": datetime(2023, 1, 2),
                "customer_name": "Jane Doe",
                "customer_email": "jane.doe@example.com",
            },
            {
                "customer_id": "3",
                "customer_created_at": datetime(2023, 1, 3),
                "customer_name": "John Smith",
                "customer_email": "john.smith@example.com",
            },
            {
                "customer_id": "4",
                "customer_created_at": datetime(2023, 1, 6),
                "customer_name": "Jane Smith",
                "customer_email": "jane.smith@example.com",
            },
            {
                "customer_id": "5",
                "customer_created_at": datetime(2023, 1, 7),
                "customer_name": "John Doe Jr",
                "customer_email": "john.doejr@example.com",
            },
        ]
        create_data_warehouse_table(self.team, customer_table_name, customer_table_data, customer_columns)

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=subscription_table_name,
            source_table_key="subscription_customer_id",
            joining_table_name=customer_table_name,
            joining_table_key="customer_id",
            field_name="subscription_customer",
        )

        return subscription_table_name

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
