import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import Mock, patch

from posthog.hogql.errors import TableAccessDeniedError

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import hogql_cohort_subquery_sql
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

from ee.models.rbac.access_control import AccessControl

WAREHOUSE_FILTERS = {
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
}


def _create_warehouse_persons_join(team: Team) -> None:
    credential = DataWarehouseCredential.objects.create(team=team, access_key="_accesskey", access_secret="_secret")
    DataWarehouseTable.objects.create(
        team=team,
        name="extended_properties",
        columns={
            "string_prop": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
            "bool_prop": {"hogql": "BooleanDatabaseField", "clickhouse": "Nullable(Bool)"},
        },
        credential=credential,
        url_pattern="",
    )
    DataWarehouseJoin.objects.create(
        team=team,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name="extended_properties",
        joining_table_key="string_prop",
        field_name="extended_properties",
    )


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestCohortRecalculationWarehouseAccessControl(BaseTest):
    def setUp(self):
        super().setUp()
        _create_warehouse_persons_join(self.team)
        self.cohort = Cohort.objects.create(team=self.team, name="warehouse-backed cohort", filters=WAREHOUSE_FILTERS)

    def test_background_recalculation_bypasses_warehouse_access_control(self):
        # Userless compile fails closed - this also proves the cohort genuinely resolves
        # through the warehouse table, so the bypass assertion below can't pass vacuously.
        with pytest.raises(TableAccessDeniedError):
            hogql_cohort_subquery_sql(self.cohort, team=self.team)

        # Recalculation always opts into the bypass, so the same cohort compiles.
        sql, _ = hogql_cohort_subquery_sql(self.cohort, team=self.team, bypass_warehouse_access_control=True)
        assert "extended_properties" in sql


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestCohortSaveWarehouseAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()
        _create_warehouse_persons_join(self.team)

    def _save_cohort(self):
        return self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "warehouse cohort", "filters": WAREHOUSE_FILTERS},
        )

    def test_denied_member_cannot_save_warehouse_cohort(self):
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")

        response = self._save_cohort()

        assert response.status_code == 400, response.content
        assert "extended_properties" in str(response.json())
        assert not Cohort.objects.filter(team=self.team).exists()

    def test_member_with_access_can_save_warehouse_cohort(self):
        response = self._save_cohort()

        assert response.status_code == 201, response.content
