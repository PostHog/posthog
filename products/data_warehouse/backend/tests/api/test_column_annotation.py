from posthog.test.base import APIBaseTest

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    WarehouseColumnAnnotation,
)

from ee.models.rbac.access_control import AccessControl


class TestWarehouseColumnAnnotation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=self.team)
        self.table = DataWarehouseTable.objects.create(
            name="stripe_charges",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="https://bucket.s3/data/*",
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.pk}/warehouse_column_annotations/{suffix}"

    def test_list_filters_by_table_id(self):
        other_table = DataWarehouseTable.objects.create(
            name="stripe_customers",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="https://bucket.s3/data/*",
        )
        WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=self.table,
            column_name="amount",
            description="charge amount in cents",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )
        WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=other_table,
            column_name="email",
            description="customer email",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

        response = self.client.get(self._url(f"?table_id={self.table.id}"))
        assert response.status_code == 200, response.json()
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["column_name"] == "amount"
        assert results[0]["description_source"] == "ai_generated"

    def test_patch_marks_as_user_edited(self):
        annotation = WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=self.table,
            column_name="amount",
            description="charge amount in cents",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

        response = self.client.patch(self._url(f"{annotation.id}/"), {"description": "amount the customer paid, USD"})
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["description"] == "amount the customer paid, USD"
        assert body["description_source"] == "user_edited"
        assert body["is_user_edited"] is True

        annotation.refresh_from_db()
        assert annotation.is_user_edited is True

    def test_create_sets_user_edited(self):
        response = self.client.post(
            self._url(),
            {"table": str(self.table.id), "column_name": "status", "description": "charge lifecycle status"},
        )
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["description_source"] == "user_edited"
        assert body["is_user_edited"] is True

    def test_cannot_annotate_table_from_another_team(self):
        other_team = self.organization.teams.create(name="other")
        other_credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=other_team)
        other_table = DataWarehouseTable.objects.create(
            name="secret",
            format="Parquet",
            team=other_team,
            credential=other_credential,
            url_pattern="https://bucket.s3/data/*",
        )

        response = self.client.post(
            self._url(),
            {"table": str(other_table.id), "column_name": "x", "description": "should fail"},
        )
        assert response.status_code == 400, response.json()

    def test_cannot_annotate_table_user_is_denied(self):
        # A user with general warehouse-table write access but an explicit "none" on this specific table
        # must not be able to create an annotation for it.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        member = self._create_user("member@posthog.com")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        # General editor access to the resource, but denied on this one table.
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=None,
            access_level="editor",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(self.table.id),
            access_level="none",
            organization_member=membership,
        )

        self.client.force_login(member)
        response = self.client.post(
            self._url(),
            {"table": str(self.table.id), "column_name": "status", "description": "should be denied"},
        )
        assert response.status_code == 403, response.json()
        assert not WarehouseColumnAnnotation.objects.for_team(self.team.pk).filter(table=self.table).exists()

    def test_table_is_immutable_on_update(self):
        # The table an annotation points at cannot change after creation — a PATCH that includes a
        # different table is ignored, not applied. Guards against re-introducing the repoint permission trap.
        other_table = DataWarehouseTable.objects.create(
            name="stripe_customers",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="https://bucket.s3/data/*",
        )
        annotation = WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=self.table,
            column_name="amount",
            description="charge amount in cents",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

        response = self.client.patch(
            self._url(f"{annotation.id}/"),
            {"table": str(other_table.id), "description": "amount the customer paid, USD"},
        )
        assert response.status_code == 200, response.json()

        annotation.refresh_from_db()
        assert annotation.table_id == self.table.id
        assert annotation.description == "amount the customer paid, USD"

    def test_duplicate_create_upserts(self):
        # Creating an annotation for a (table, column) that already has one updates it in place rather than
        # 500ing on the unique constraint — so agents can call create idempotently.
        first = self.client.post(
            self._url(),
            {"table": str(self.table.id), "column_name": "amount", "description": "first"},
        )
        assert first.status_code == 201, first.json()
        second = self.client.post(
            self._url(),
            {"table": str(self.table.id), "column_name": "amount", "description": "second"},
        )
        assert second.status_code == 201, second.json()

        annotations = WarehouseColumnAnnotation.objects.for_team(self.team.pk).filter(
            table=self.table, column_name="amount"
        )
        assert annotations.count() == 1
        annotation = annotations.first()
        assert annotation is not None
        assert annotation.description == "second"

    def test_cannot_delete_annotation_on_view_only_table(self):
        # A user who can only view a table (so its annotations are readable) must not be able to delete
        # them — destroy requires editor access on the annotation's table.
        annotation = WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=self.table,
            column_name="amount",
            description="charge amount in cents",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        member = self._create_user("member@posthog.com")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        # Viewer access on this table: the annotation is readable, but not deletable.
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(self.table.id),
            access_level="viewer",
            organization_member=membership,
        )

        self.client.force_login(member)
        response = self.client.delete(self._url(f"{annotation.id}/"))
        assert response.status_code == 403, getattr(response, "data", response.status_code)
        assert WarehouseColumnAnnotation.objects.for_team(self.team.pk).filter(id=annotation.id).exists()

    def test_viewer_cannot_edit_annotation_on_view_only_table(self):
        # A user with only view access to a table can read its annotations but must not edit them —
        # perform_update requires editor access on the annotation's table (distinct path from destroy).
        annotation = WarehouseColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            table=self.table,
            column_name="amount",
            description="charge amount in cents",
            description_source=WarehouseColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        member = self._create_user("member@posthog.com")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(self.table.id),
            access_level="viewer",
            organization_member=membership,
        )

        self.client.force_login(member)
        response = self.client.patch(self._url(f"{annotation.id}/"), {"description": "changed"})
        assert response.status_code == 403, getattr(response, "data", response.status_code)

        annotation.refresh_from_db()
        assert annotation.description == "charge amount in cents"
