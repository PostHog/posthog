from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import GroupUsageMetric
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.test.persons import create_group_type_mapping

from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable


class GroupUsageMetricViewSetTestCase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.group_type = create_group_type_mapping(
            team=self.team, project=self.project, group_type="organization", group_type_index=0
        )
        self.url = f"/api/projects/{self.team.id}/groups_types/{str(self.group_type.group_type_index)}/metrics"

        self.other_org = Organization.objects.create(name="other org")
        self.other_team = Team.objects.create(organization=self.other_org, name="other team")
        self.other_group_type = create_group_type_mapping(
            team=self.other_team, project_id=self.other_team.project_id, group_type="company", group_type_index=0
        )
        self.other_url = (
            f"/api/projects/{self.other_team.id}/groups_types/{str(self.other_group_type.group_type_index)}/metrics"
        )

    def assertFields(self, data, metric):
        self.assertEqual(data["id"], str(metric.id))
        self.assertEqual(data["name"], metric.name)
        self.assertEqual(data["format"], metric.format)
        self.assertEqual(data["interval"], metric.interval)
        self.assertEqual(data["display"], metric.display)
        self.assertEqual(data["filters"], metric.filters)

    def _create_metric(self, **kwargs):
        defaults = {
            "team": self.team,
            "group_type_index": self.group_type.group_type_index,
            "name": "Events",
            "filters": {"foo": "bar"},
        }
        defaults.update(kwargs)
        return GroupUsageMetric.objects.create(**defaults)

    def test_list(self):
        metric = self._create_metric()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFields(response.json()["results"][0], metric)

    def test_create(self):
        payload = {"name": "Events", "filters": {"foo": "bar"}}

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        metric = GroupUsageMetric.objects.get(id=response.json().get("id"))
        self.assertFields(response.json(), metric)
        self.assertEqual(metric.team, self.team, "Should set team automatically")
        self.assertEqual(
            metric.group_type_index, self.group_type.group_type_index, "Should set group_type_index automatically"
        )
        self.assertIsNotNone(metric.bytecode, "Should set bytecode automatically")

    def test_retrieve(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFields(response.json(), metric)

    def test_update(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        payload = {
            "name": "Updated Events",
            "format": "currency",
            "interval": 30,
            "display": "sparkline",
            "filters": {"updated": "value"},
        }

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Updated Events")
        self.assertEqual(metric.format, "currency")
        self.assertEqual(metric.interval, 30)
        self.assertEqual(metric.display, "sparkline")
        self.assertEqual(metric.filters, {"updated": "value"})
        self.assertFields(response.json(), metric)

    def test_delete(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GroupUsageMetric.objects.filter(id=metric.id).exists())

    def test_partial_update(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        payload = {"name": "Partially Updated Events"}

        response = self.client.patch(url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Partially Updated Events")
        self.assertEqual(metric.format, "numeric", "Should remain unchanged")
        self.assertEqual(metric.interval, 7, "Should remain unchanged")
        self.assertEqual(metric.display, "number", "Should remain unchanged")

    def test_delete_nonexistent(self):
        fake_id = "00000000-0000-0000-0000-000000000000"
        url = f"{self.url}/{fake_id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_nonexistent(self):
        fake_id = "00000000-0000-0000-0000-000000000000"
        url = f"{self.url}/{fake_id}"
        payload = {"name": "Updated Events"}

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_access(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthorized_team_access(self):
        self._create_metric(group_type_index=self.other_group_type.group_type_index, team=self.other_team)

        response = self.client.get(self.other_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_access(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_creation(self):
        payload = {"name": "Unauthorized Events"}

        response = self.client.post(self.other_url, payload)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_modification(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"
        payload = {"name": "Hacked Events"}

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_deletion(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

        self.assertTrue(GroupUsageMetric.objects.filter(id=other_metric.id).exists())

    def test_non_admin_cannot_update_metric(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        # Grant member-level (not admin) project access so the request reaches the serializer
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
        )

        response = self.client.patch(url, {"name": "Should not update"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Events")

    def test_admin_can_update_metric(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(url, {"name": "Updated by admin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Updated by admin")

    def _create_dw_table(self, name: str = "stripe_charges"):
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        return DataWarehouseTable.objects.create(
            team=self.team,
            name=name,
            credential=credential,
            url_pattern="http://example.com/{name}",
            columns={
                "customer_id": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                "created": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField", "valid": True},
                "amount": {"clickhouse": "Float64", "hogql": "FloatDatabaseField", "valid": True},
            },
        )

    def test_create_data_warehouse_metric(self):
        self._create_dw_table()
        payload = {
            "name": "DW signups",
            "math": "count",
            "filters": {
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        metric = GroupUsageMetric.objects.get(id=response.json()["id"])
        self.assertEqual(metric.filters["source"], "data_warehouse")
        self.assertEqual(metric.filters["table_name"], "stripe_charges")

    def test_create_data_warehouse_metric_rejects_missing_fields(self):
        self._create_dw_table()
        payload = {
            "name": "DW signups",
            "filters": {"source": "data_warehouse", "table_name": "stripe_charges"},
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "filters")

    def test_create_data_warehouse_metric_rejects_unknown_table(self):
        payload = {
            "name": "DW signups",
            "filters": {
                "source": "data_warehouse",
                "table_name": "no_such_table",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "filters")

    @parameterized.expand(
        [
            ("duplicate_name_on_create", "post", {"name": "Events", "filters": {}}, 400, "name"),
            ("duplicate_name_on_rename", "patch", {"name": "Events"}, 400, "name"),
            ("own_name_on_update", "patch", {"name": "Signups"}, 200, None),
            (
                "test_account_cohort_filter",
                "post",
                {"name": "Pageviews", "filters": {"filter_test_accounts": True}},
                400,
                "filters",
            ),
        ]
    )
    def test_save_rejects_invalid_input_with_400(self, _name, method, payload, expected_status, expected_attr):
        self._create_metric(name="Events")
        signups = self._create_metric(name="Signups")
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": 999999}]
        self.team.save()
        url = self.url if method == "post" else f"{self.url}/{signups.id}"

        response = getattr(self.client, method)(url, payload, format="json")

        self.assertEqual(response.status_code, expected_status, response.json())
        self.assertEqual(response.json().get("attr"), expected_attr)

    def test_create_data_warehouse_metric_accepts_table_with_null_deleted(self):
        table = self._create_dw_table()
        table.deleted = None
        table.save()

        payload = {
            "name": "DW signups",
            "filters": {
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

    def test_create_data_warehouse_metric_rejects_soft_deleted_table(self):
        table = self._create_dw_table()
        table.deleted = True
        table.save()

        payload = {
            "name": "DW signups",
            "filters": {
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "filters")

    def test_create_data_warehouse_sum_requires_math_property(self):
        self._create_dw_table()
        payload = {
            "name": "DW revenue",
            "math": "sum",
            "filters": {
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "math_property")

    def test_create_metric_rejects_unknown_source(self):
        payload = {
            "name": "Bogus",
            "filters": {"source": "something_else"},
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "filters")
