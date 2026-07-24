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

# The realistic way a cohort reaches a warehouse table: a behavioral filter whose hogql
# event filter traverses the persons warehouse join (cohort filters reject direct
# data_warehouse_* property types at the pydantic layer).
WAREHOUSE_FILTERS = {
    "properties": {
        "type": "AND",
        "values": [
            {
                "type": "behavioral",
                "key": "$pageview",
                "value": "performed_event",
                "event_type": "events",
                "explicit_datetime": "-30d",
                "event_filters": [{"type": "hogql", "key": "person.extended_properties.bool_prop = 'true'"}],
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
        assert "Can't save this cohort" in str(response.json())
        assert "extended_properties" in str(response.json())
        assert not Cohort.objects.filter(team=self.team).exists()

    def test_member_with_access_can_save_warehouse_cohort(self):
        response = self._save_cohort()

        assert response.status_code == 201, response.content

    def test_denied_member_cannot_save_query_cohort_over_warehouse_table(self):
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {
                "name": "query cohort",
                "is_static": True,
                "query": {"kind": "HogQLQuery", "query": "SELECT string_prop FROM extended_properties"},
            },
        )

        assert response.status_code == 400, response.content
        assert "Can't save this cohort" in str(response.json())
        assert "extended_properties" in str(response.json())

    def test_denied_member_cannot_reactivate_warehouse_groups_by_clearing_filters(self):
        # Clearing filters makes Cohort.properties fall back to preserved legacy groups, so the
        # gate must validate the effective post-save definition, not just the payload fields.
        cohort = Cohort.objects.create(
            team=self.team,
            name="dormant warehouse groups",
            filters={"properties": {"type": "AND", "values": []}},
            groups=[{"properties": WAREHOUSE_FILTERS["properties"]["values"]}],
        )
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.pk}/",
            {"filters": None},
        )

        assert response.status_code == 400, response.content
        assert "Can't save this cohort" in str(response.json())
        assert "extended_properties" in str(response.json())

    def test_denied_member_cannot_update_via_legacy_groups(self):
        cohort = Cohort.objects.create(team=self.team, name="plain cohort")
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")

        # Legacy `groups` writes skip field-level validate_filters - the object-level gate must
        # still catch a warehouse reference smuggled in through them.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.pk}/",
            {"groups": [{"properties": WAREHOUSE_FILTERS["properties"]["values"]}]},
        )

        assert response.status_code == 400, response.content
        assert "Can't save this cohort" in str(response.json())
        assert "extended_properties" in str(response.json())
