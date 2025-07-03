from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery
from posthog.models import Cohort
from posthog.test.base import BaseTest
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable


class TestHogQLCohortQuery(BaseTest):
    def test_data_warehouse_field_resolution_works_with_team_in_context(self):
        credential = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        DataWarehouseTable.objects.create(
            name="bigquery_raw_monolith_user",
            format="Parquet",
            team=self.team,
            credential=credential,
            url_pattern="s3://test/*",
            columns={
                "id": "String",
                "subscription_id": "String",
                "plan_id": "String",
            },
        )

        # Create a cohort with HogQL expressions that reference the data warehouse table
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "open_application_web",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "negation": False,
                                    "event_type": "events",
                                    "event_filters": [
                                        {
                                            "key": "bigquery_raw_monolith_user.subscription_id = '12345'",
                                            "type": "hogql",
                                            "value": None,
                                        }
                                    ],
                                    "explicit_datetime": "2025-06-01",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Try to instantiate HogQLCohortQuery and generate the query
        # This should now work without errors since the context includes the team object
        HogQLCohortQuery(cohort=cohort)
