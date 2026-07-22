import pytest
from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from posthog.hogql.errors import TableAccessDeniedError

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import hogql_cohort_subquery_sql
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestCohortRecalculationWarehouseAccessControl(BaseTest):
    def setUp(self):
        super().setUp()
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="extended_properties",
            columns={
                "string_prop": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
                "bool_prop": {"hogql": "BooleanDatabaseField", "clickhouse": "Nullable(Bool)"},
            },
            credential=credential,
            url_pattern="",
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="extended_properties",
            joining_table_key="string_prop",
            field_name="extended_properties",
        )
        self.cohort = Cohort.objects.create(
            team=self.team,
            name="warehouse-backed cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "data_warehouse_person_property",
                            "key": "extended_properties.bool_prop",
                            "value": "true",
                            "operator": "exact",
                        }
                    ],
                }
            },
        )

    def test_background_recalculation_bypasses_warehouse_access_control(self):
        # Userless compile fails closed - this also proves the cohort genuinely resolves
        # through the warehouse table, so the bypass assertion below can't pass vacuously.
        with pytest.raises(TableAccessDeniedError):
            hogql_cohort_subquery_sql(self.cohort, team=self.team)

        # The background recalculation path opts into the bypass, so the same cohort compiles.
        sql, _ = hogql_cohort_subquery_sql(self.cohort, team=self.team, bypass_warehouse_access_control=True)
        assert "extended_properties" in sql
