from uuid import uuid4

import pytest

from rest_framework import status

from posthog.hogql.database.database import Database

from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin


@pytest.mark.ee
class TestExpressionAccessControl(WarehouseAccessControlTestMixin):
    # DataWarehouseExpressionViewSet scope_object = "warehouse_view", which inherits from
    # "warehouse_objects" in RESOURCE_INHERITANCE_MAP — grant at the umbrella.
    resource = "warehouse_objects"

    def _url(self, expression_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.pk}/warehouse_expressions/"
        return f"{base}{expression_id}/" if expression_id else base

    def test_object_grant_on_unrelated_view_does_not_authorize_expressions(self):
        expression_id = self.client.post(
            self._url(),
            {"table_name": "events", "field_name": "browser", "expression": "properties.$browser"},
        ).json()["id"]

        self._create_project_default(access_level="none")
        # An object-level grant on one unrelated saved view passes the generic resource
        # permission check; it must not extend to other users' expressions.
        self._create_access_control(
            self.viewer_user, resource="warehouse_view", resource_id=str(uuid4()), access_level="editor"
        )
        self.client.force_login(self.viewer_user)

        list_response = self.client.get(self._url())
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.json()["results"], [])

        patch_response = self.client.patch(self._url(expression_id), {"expression": "upper(event)"})
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN, patch_response.content)

        delete_response = self.client.delete(self._url(expression_id))
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN, delete_response.content)

    def test_object_denied_expression_is_not_injected_into_queries(self):
        expression_id = self.client.post(
            self._url(),
            {"table_name": "events", "field_name": "browser", "expression": "properties.$browser"},
        ).json()["id"]
        self._create_access_control(
            self.viewer_user, resource="warehouse_view", resource_id=expression_id, access_level="none"
        )

        for user, should_have_field in ((self.viewer_user, False), (self.editor_user, True)):
            sources = Database._fetch_sources(team=self.team, user=user)
            sources.is_hogql_warehouse_access_control_enabled = True
            database = Database._build_from_sources(sources)
            self.assertEqual("browser" in database.get_table("events").fields, should_have_field, user.email)
