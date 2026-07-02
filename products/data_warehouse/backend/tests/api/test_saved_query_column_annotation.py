from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.data_modeling.backend.facade.models import (
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryColumnAnnotation,
)

from ee.models.rbac.access_control import AccessControl


class TestDataWarehouseSavedQueryColumnAnnotation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="paid_users",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.pk}/saved_query_column_annotations/{suffix}"

    def test_create_sets_user_edited(self):
        response = self.client.post(
            self._url(),
            {"saved_query": str(self.view.id), "column_name": "status", "description": "subscription status"},
        )
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["description_source"] == "user_edited"
        assert body["is_user_edited"] is True

    def test_list_filters_by_saved_query_id(self):
        other_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="churned_users",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
        )
        DataWarehouseSavedQueryColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            saved_query=self.view,
            column_name="status",
            description="subscription status",
            description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.AI_GENERATED,
        )
        DataWarehouseSavedQueryColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            saved_query=other_view,
            column_name="reason",
            description="churn reason",
            description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.AI_GENERATED,
        )

        response = self.client.get(self._url(f"?saved_query_id={self.view.id}"))
        assert response.status_code == 200, response.json()
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["column_name"] == "status"

    def test_cannot_annotate_view_from_another_team(self):
        other_team = self.organization.teams.create(name="other")
        other_view = DataWarehouseSavedQuery.objects.create(
            team=other_team,
            name="secret_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
        )

        response = self.client.post(
            self._url(),
            {"saved_query": str(other_view.id), "column_name": "x", "description": "should fail"},
        )
        assert response.status_code == 400, response.json()

    def test_cannot_annotate_deleted_view(self):
        deleted_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="old_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            deleted=True,
        )
        response = self.client.post(
            self._url(),
            {"saved_query": str(deleted_view.id), "column_name": "x", "description": "should fail"},
        )
        assert response.status_code == 400, response.json()

    def test_can_annotate_endpoint_origin_view(self):
        # Endpoint-origin views are hidden from the saved-query list UI, but their columns still benefit
        # from AI-facing descriptions, so they are annotatable.
        endpoint_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_endpoint",
            query={"kind": "HogQLQuery", "query": "select 1"},
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        response = self.client.post(
            self._url(),
            {"saved_query": str(endpoint_view.id), "column_name": "count", "description": "row count"},
        )
        assert response.status_code == 201, response.json()

    def test_duplicate_create_upserts(self):
        first = self.client.post(
            self._url(),
            {"saved_query": str(self.view.id), "column_name": "status", "description": "first"},
        )
        assert first.status_code == 201, first.json()
        second = self.client.post(
            self._url(),
            {"saved_query": str(self.view.id), "column_name": "status", "description": "second"},
        )
        assert second.status_code == 201, second.json()

        annotations = DataWarehouseSavedQueryColumnAnnotation.objects.for_team(self.team.pk).filter(
            saved_query=self.view, column_name="status"
        )
        assert annotations.count() == 1
        annotation = annotations.first()
        assert annotation is not None
        assert annotation.description == "second"

    @parameterized.expand(
        [
            # (name, columns, column_name, expected_status)
            ("known_column", {"status": {"clickhouse": "String"}}, "status", 201),
            ("unknown_column_when_known", {"status": {"clickhouse": "String"}}, "typo", 400),
            ("unknown_column_when_columns_empty", {}, "any_draft_column", 201),
            ("view_level_always_allowed", {"status": {"clickhouse": "String"}}, "", 201),
        ]
    )
    def test_column_name_validation(self, _name, columns, column_name, expected_status):
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=f"view_{_name}",
            query={"kind": "HogQLQuery", "query": "select 1"},
            columns=columns,
        )
        response = self.client.post(
            self._url(),
            {"saved_query": str(view.id), "column_name": column_name, "description": "d"},
        )
        assert response.status_code == expected_status, response.json()

    def test_cannot_annotate_view_user_is_denied(self):
        # A member with general editor access but an explicit "none" on this specific view must not be able
        # to annotate it — perform_create re-checks editor access on the target view. Also guards against a
        # schema leak: an invalid column_name must NOT echo the view's real columns before the access check.
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="secret_metrics",
            query={"kind": "HogQLQuery", "query": "select 1"},
            columns={"revenue": {"clickhouse": "Int64"}},
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
            resource="warehouse_view",
            resource_id=None,
            access_level="editor",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(view.id),
            access_level="none",
            organization_member=membership,
        )

        self.client.force_login(member)
        response = self.client.post(
            self._url(),
            {"saved_query": str(view.id), "column_name": "typo_column", "description": "should be denied"},
        )
        assert response.status_code == 403, response.json()
        assert "revenue" not in response.content.decode()
        assert not DataWarehouseSavedQueryColumnAnnotation.objects.for_team(self.team.pk).exists()

    @parameterized.expand(["edit", "delete"])
    def test_viewer_cannot_write_annotation_on_view_only_view(self, action):
        # A viewer on a view can read its annotations but cannot edit (perform_update) or delete
        # (perform_destroy) them — both write paths re-check editor access on the view, and they are
        # distinct code paths, so both are exercised here.
        annotation = DataWarehouseSavedQueryColumnAnnotation.objects.for_team(self.team.pk).create(
            team=self.team,
            saved_query=self.view,
            column_name="status",
            description="subscription status",
            description_source=DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.AI_GENERATED,
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
            resource="warehouse_view",
            resource_id=str(self.view.id),
            access_level="viewer",
            organization_member=membership,
        )

        self.client.force_login(member)
        if action == "delete":
            response = self.client.delete(self._url(f"{annotation.id}/"))
        else:
            response = self.client.patch(self._url(f"{annotation.id}/"), {"description": "changed"})
        assert response.status_code == 403, getattr(response, "data", response.status_code)

        annotation.refresh_from_db()
        assert annotation.description == "subscription status"
