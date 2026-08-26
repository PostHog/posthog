from datetime import timedelta

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Edge, Node, NodeType
from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_tools.backend.models.datawarehouse_saved_query_folder import DataWarehouseSavedQueryFolder
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


@pytest.mark.ee
class TestDataWarehouseSavedQueryAccessControl(WarehouseAccessControlTestMixin):
    # Resource-level AC uses warehouse_table (views inherit from tables).
    # Object-level AC on a specific saved query still keys on "warehouse_view"
    # because model_to_resource(DataWarehouseSavedQuery) == "warehouse_view".
    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
        )

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_queries/"

    def _detail_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/"

    @parameterized.expand(
        [
            # (access_level, method, expected_status, patch_body)
            ("viewer", "GET", status.HTTP_200_OK, None),
            ("viewer", "PATCH", status.HTTP_403_FORBIDDEN, {"name": "updated"}),
            ("viewer", "DELETE", status.HTTP_403_FORBIDDEN, None),
            ("editor", "GET", status.HTTP_200_OK, None),
            ("editor", "PATCH", status.HTTP_200_OK, {"name": "updated_name"}),
            ("none", "GET", status.HTTP_403_FORBIDDEN, None),
        ]
    )
    def test_access_level_matrix(self, access_level, method, expected_status, patch_body):
        user = (
            self.viewer_user
            if access_level == "viewer"
            else self.editor_user
            if access_level == "editor"
            else self.no_access_user
        )
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)

        if method == "GET":
            response = self.client.get(self._detail_url())
        elif method == "PATCH":
            response = self.client.patch(self._detail_url(), data=patch_body)
        elif method == "DELETE":
            response = self.client.delete(self._detail_url())
        else:
            raise AssertionError(f"Unsupported method {method}")

        self.assertEqual(response.status_code, expected_status)

    def test_viewer_can_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_200_OK)

    def test_project_default_none_blocks_non_creator_retrieve(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_list_filters_to_own_queries_when_explicit_viewer(self):
        # Creator sees their own query; an object-level 'none' on another user's query excludes it.
        other_user = User.objects.create_and_join(self.organization, "otheruser@posthog.com", "testtest")
        other_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="other_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=other_user,
        )
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        # Object-level AC for saved queries uses "warehouse_view" (the model's own resource).
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(other_query.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.user)
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [q["id"] for q in response.json()["results"]]
        self.assertIn(str(self.saved_query.id), ids)
        self.assertNotIn(str(other_query.id), ids)

    def test_non_creator_list_blocked_with_project_default_none(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_explicit_viewer_access_allows_list_with_project_default_none(self):
        self._create_project_default(access_level="none")
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_200_OK)

    def test_object_level_access_blocks_specific_query(self):
        # Grant viewer at resource level (warehouse_table), then deny object-level on this specific view.
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(
            self.viewer_user, resource="warehouse_view", resource_id=str(self.saved_query.id), access_level="none"
        )
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_user_access_level_field_is_present_in_response(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("user_access_level"), "viewer")

    def test_upsert_create_respects_object_level_none(self):
        # Regression: POST with an existing query's name performs an UPSERT-update.
        # Object-level access controls must still apply even though get_object() isn't called.
        self._create_access_control(self.editor_user, access_level="editor")  # resource-level editor
        self._create_access_control(
            self.editor_user, resource="warehouse_view", resource_id=str(self.saved_query.id), access_level="none"
        )  # but object-level none for this specific view
        self.client.force_login(self.editor_user)
        response = self.client.post(
            self._list_url(),
            data={"name": self.saved_query.name, "query": {"kind": "HogQLQuery", "query": "select 2"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Confirm the query was NOT overwritten
        self.saved_query.refresh_from_db()
        self.assertEqual(self.saved_query.query, {"kind": "HogQLQuery", "query": "select 1"})

    def test_resource_level_row_on_child_alone_has_no_effect(self):
        # Contract: warehouse_view inherits from warehouse_objects, so resource-level rows
        # keyed on warehouse_view (without resource_id) are intentionally bypassed — only
        # the umbrella warehouse_objects scope counts. The distinguishing assertion is that
        # creator bypass (resolved via access_level_for_object) still returns "manager" on
        # the user's own query, even with a child-only `none` row that would otherwise
        # short-circuit resource access. If has_access_levels_for_resource ever started
        # honoring child rows it would route through access_level_for_resource and lose
        # creator bypass, returning the default ("editor") instead.
        own_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="own_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.viewer_user,
        )
        AccessControl.objects.create(team=self.team, resource="warehouse_view", access_level="none")
        self.client.force_login(self.viewer_user)

        url = f"/api/environments/{self.team.pk}/warehouse_saved_queries/{own_query.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Creator bypass: highest level for warehouse_view is "manager".
        self.assertEqual(response.json().get("user_access_level"), "manager")

    def test_object_level_access_grants_through_resource_default_none(self):
        # When the project default is 'none' (no resource access), an object-level grant on a
        # specific saved query still lets the user retrieve and edit that query, while other
        # queries remain blocked. This relies on AccessControlPermission falling back to
        # has_any_specific_access_for_resource.
        other_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="other_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
        )
        self._create_project_default(access_level="none")
        # Grant editor on this specific saved query (object-level row keyed on warehouse_view).
        self._create_access_control(
            self.viewer_user,
            resource="warehouse_view",
            resource_id=str(self.saved_query.id),
            access_level="editor",
        )
        self.client.force_login(self.viewer_user)

        # The granted query is retrievable and editable.
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_200_OK)
        patch_response = self.client.patch(
            self._detail_url(), data={"name": "renamed_via_object_grant"}, content_type="application/json"
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        # A different query without an object-level grant stays blocked.
        other_url = f"/api/environments/{self.team.pk}/warehouse_saved_queries/{other_query.id}/"
        self.assertEqual(self.client.get(other_url).status_code, status.HTTP_403_FORBIDDEN)


@pytest.mark.ee
class TestDataWarehouseSavedQueryFolderAccessControl(WarehouseAccessControlTestMixin):
    # Folder resource-level AC goes through warehouse_table via inheritance.
    # Object-level AC on specific folders still keys on "warehouse_view".
    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.folder = DataWarehouseSavedQueryFolder.objects.create(
            team=self.team, name="Marketing", created_by=self.user
        )

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_query_folders/"

    def _detail_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_query_folders/{self.folder.id}/"

    def test_folder_list_works_without_restrictions(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_200_OK)

    def test_folder_retrieve_respects_warehouse_view_default(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_folder_viewer_can_retrieve(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_folder_viewer_cannot_update(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.patch(self._detail_url(), data={"name": "renamed"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_folder_user_access_level_field_is_present(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("user_access_level"), "viewer")

    def test_folder_object_level_none_blocks_specific_folder(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(
            self.viewer_user, resource="warehouse_view", resource_id=str(self.folder.id), access_level="none"
        )
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

    def test_folder_creator_list_filters_out_blocked_other_folder(self):
        # Creator has resource access, but an object-level 'none' on another user's folder excludes it from their list.
        # Creator bypass applies at the queryset filter layer, not at has_permission — so the creator needs
        # at least resource-level access for the list endpoint to return 200.
        other_user = User.objects.create_and_join(self.organization, "otheruser@posthog.com", "testtest")
        other_folder = DataWarehouseSavedQueryFolder.objects.create(team=self.team, name="Other", created_by=other_user)
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        # Object-level AC on folders uses "warehouse_view" (the model's own resource).
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(other_folder.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.user)
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Folder endpoint is unpaginated - response is a flat list of folder dicts
        ids = [f["id"] for f in response.json()]
        self.assertIn(str(self.folder.id), ids)
        self.assertNotIn(str(other_folder.id), ids)


@pytest.mark.ee
@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestMaterializationRequiresUnderlyingAccess(WarehouseAccessControlTestMixin):
    """Enabling materialization publishes a view's rows under the view's own access rules, so it has
    to be gated on the requester's access to what the query reads - not just on the view."""

    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.credential = DataWarehouseCredential.objects.create(
            access_key="key", access_secret="secret", team=self.team
        )
        self.table = DataWarehouseTable.objects.create(
            name="restricted_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="s3://bucket/restricted/*",
            columns={"id": "String"},
        )
        # Authored by someone who could read the table; the restricted user only materializes it.
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="view_over_restricted",
            query={"kind": "HogQLQuery", "query": "select id from restricted_table"},
            created_by=self.user,
        )
        self._create_access_control(self.editor_user, access_level="editor")
        self._create_access_control(
            self.editor_user, resource="warehouse_table", resource_id=str(self.table.id), access_level="none"
        )
        self.client.force_login(self.editor_user)

    def _base(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.view.id}"

    def test_materialize_denied_when_the_query_reads_a_denied_table(self):
        response = self.client.post(f"{self._base()}/materialize/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.view.refresh_from_db()
        self.assertFalse(self.view.is_materialized)

    def test_scheduling_denied_when_the_query_reads_a_denied_table(self):
        # Same grant by another name: a sync frequency is what actually schedules the runs.
        response = self.client.patch(f"{self._base()}/", {"sync_frequency": "24hour"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.view.refresh_from_db()
        self.assertIsNone(self.view.sync_frequency_interval)

    def test_running_the_dag_node_is_denied_when_the_query_reads_a_denied_table(self):
        # The run workflow sets is_materialized itself, so running a node publishes the same rows
        # that `materialize` would - a separate door onto the same declassification.
        dag = DAG.objects.create(team=self.team, name="dag")
        node = Node.objects.create(
            team=self.team, dag=dag, name=self.view.name, saved_query=self.view, type=NodeType.VIEW
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/data_modeling_nodes/{node.id}/run/",
            {"direction": "downstream"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_materializing_the_node_is_denied_when_the_query_reads_a_denied_table(self):
        # The single-node endpoint dispatches the same materialization workflow as `run`, so it is
        # yet another door onto the same declassification.
        dag = DAG.objects.create(team=self.team, name="dag")
        node = Node.objects.create(
            team=self.team, dag=dag, name=self.view.name, saved_query=self.view, type=NodeType.VIEW
        )

        response = self.client.post(f"/api/environments/{self.team.pk}/data_modeling_nodes/{node.id}/materialize/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_materialize_allowed_without_a_table_denial(self):
        AccessControl.objects.filter(resource="warehouse_table", resource_id=str(self.table.id)).delete()

        response = self.client.post(f"{self._base()}/materialize/")

        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@pytest.mark.ee
class TestSyncFrequencyBoundsAccessControl(WarehouseAccessControlTestMixin):
    """The cadence bounds name what blocks a cadence, so they answer to the same grants the rest does."""

    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.upstream = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="upstream_view",
            query={"kind": "HogQLQuery", "query": "select 1 as event"},
            created_by=self.user,
        )
        self.consumer = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="consumer_view",
            query={"kind": "HogQLQuery", "query": "select event from upstream_view"},
            created_by=self.user,
        )
        dag = DAG.objects.create(team=self.team, name="dag")
        self.upstream_node = Node.objects.create(
            team=self.team, dag=dag, name=self.upstream.name, saved_query=self.upstream, type=NodeType.VIEW
        )
        self.consumer_node = Node.objects.create(
            team=self.team, dag=dag, name=self.consumer.name, saved_query=self.consumer, type=NodeType.VIEW
        )
        Edge.objects.create(team=self.team, dag=dag, source=self.upstream_node, target=self.consumer_node)
        set_declared_target(self.consumer_node, timedelta(hours=6))

    def _tiered(self):
        return (
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == "data-modeling-backend-v2",
            ),
            patch(
                "products.data_modeling.backend.logic.schedule_reconcile.tiered_schedules_enabled",
                return_value=True,
            ),
        )

    def _read_upstream(self) -> tuple[dict, str]:
        v2, tiered = self._tiered()
        with v2, tiered:
            response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.upstream.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()["sync_frequency_bounds"], response.content.decode()

    def _deny_the_consumer(self, user):
        self._create_access_control(
            user, resource="warehouse_view", resource_id=str(self.consumer.id), access_level="none"
        )

    def test_a_denied_consumer_sets_the_bound_without_being_named(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._deny_the_consumer(self.viewer_user)
        self.client.force_login(self.viewer_user)

        bounds, body = self._read_upstream()

        # The bound itself survives: the caller still learns 24hour is out, and that a consumer did it.
        self.assertEqual(bounds["ceiling"]["label"], "6 hours")
        self.assertIsNone(bounds["ceiling"]["blocker"])
        blocked = {option["cadence"]: option for option in bounds["options"] if not option["allowed"]}
        self.assertEqual(blocked["24hour"]["blocked_by"], "consumer")
        self.assertIsNone(blocked["24hour"]["blocker"])
        # Neither the name nor the node id reaches the wire.
        self.assertNotIn("consumer_view", body)
        self.assertNotIn(str(self.consumer_node.id), body)

    def test_the_same_consumer_is_named_for_a_caller_who_may_read_it(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        bounds, body = self._read_upstream()

        self.assertEqual(bounds["ceiling"]["blocker"]["name"], "consumer_view")
        self.assertEqual(bounds["ceiling"]["blocker"]["id"], str(self.consumer_node.id))
        self.assertIn("consumer_view", body)

    def test_a_refused_cadence_withholds_the_name_the_read_withheld(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self._deny_the_consumer(self.editor_user)
        self.client.force_login(self.editor_user)

        v2, tiered = self._tiered()
        with v2, tiered, patch("products.data_modeling.backend.logic.schedule_reconcile.maybe_reconcile_dag"):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.upstream.id}/",
                {"sync_frequency": "24hour"},
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        detail = response.content.decode()
        self.assertNotIn("consumer_view", detail)
        self.assertIn("6 hours", detail)

    def test_a_refused_cadence_names_the_consumer_for_a_caller_who_may_read_it(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        v2, tiered = self._tiered()
        with v2, tiered, patch("products.data_modeling.backend.logic.schedule_reconcile.maybe_reconcile_dag"):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.upstream.id}/",
                {"sync_frequency": "24hour"},
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertIn("consumer_view", response.content.decode())

    def test_a_refusal_names_nothing_when_the_caller_passes_no_visible_names(self):
        """The default the endpoints API depends on: `schedule_materialization` re-raises this
        refusal and the endpoints materialization view returns its text verbatim, with no per-user
        name map to hand down. Naming by default there would leak past every grant."""
        from products.data_modeling.backend.facade.api import (
            UnsatisfiableFrequencyError,
            apply_saved_query_frequency_target,
        )

        with patch("products.data_modeling.backend.logic.schedule_reconcile.maybe_reconcile_dag"):
            with self.assertRaises(UnsatisfiableFrequencyError) as caught:
                apply_saved_query_frequency_target(self.upstream, timedelta(days=1))

        message = str(caught.exception)
        self.assertNotIn("consumer_view", message)
        self.assertNotIn(str(self.consumer_node.id), message)
        # Still actionable: it names the cadence to pick instead, just not who withheld the other.
        self.assertIn("6 hours", message)


@pytest.mark.ee
class TestSyncFrequencyTableBlockerAccessControl(WarehouseAccessControlTestMixin):
    """A source table sets the floor, and is named only for a caller who may read the table itself."""

    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="downstream_view",
            query={"kind": "HogQLQuery", "query": "select 1 as event"},
            created_by=self.user,
        )
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="posthog_test_",
        )
        # The FK, not just the schema link: it is what `warehouse_table` falls back through, and
        # what the import pipeline sets on a real imported table.
        self.table = DataWarehouseTable.objects.create(
            name="stripe_charges", team=self.team, external_data_source=self.source
        )
        ExternalDataSchema.objects.create(
            name="stripe_charges",
            team=self.team,
            source=self.source,
            table=self.table,
            sync_frequency_interval=timedelta(hours=6),
        )
        dag = DAG.objects.create(team=self.team, name="dag")
        source_node = Node.objects.create(
            team=self.team,
            dag=dag,
            name="stripe_charges",
            type=NodeType.TABLE,
            properties={"origin": "warehouse", "warehouse_table_id": str(self.table.id)},
        )
        self.view_node = Node.objects.create(
            team=self.team, dag=dag, name=self.view.name, saved_query=self.view, type=NodeType.VIEW
        )
        Edge.objects.create(team=self.team, dag=dag, source=source_node, target=self.view_node)

    def _read_view(self) -> tuple[dict, str]:
        with (
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == "data-modeling-backend-v2",
            ),
            patch(
                "products.data_modeling.backend.logic.schedule_reconcile.tiered_schedules_enabled",
                return_value=True,
            ),
        ):
            response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.view.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()["sync_frequency_bounds"], response.content.decode()

    def test_the_source_table_is_named_for_a_caller_who_may_read_it(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        bounds, body = self._read_view()

        self.assertEqual(bounds["floor"]["label"], "6 hours")
        self.assertEqual(bounds["floor"]["blocker"]["name"], "stripe_charges")
        self.assertIn("stripe_charges", body)

    @parameterized.expand(
        [
            # Denying the table itself, and denying the source it came from: `warehouse_table` falls
            # back to `external_data_source`, so a deny on the source has to withhold the name too.
            ("table_denied", "warehouse_table"),
            ("source_denied", "external_data_source"),
        ]
    )
    def test_a_denied_source_table_sets_the_floor_without_being_named(self, _name, resource):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(
            self.viewer_user,
            resource=resource,
            resource_id=str(self.table.id if resource == "warehouse_table" else self.source.id),
            access_level="none",
        )
        self.client.force_login(self.viewer_user)

        bounds, body = self._read_view()

        # The floor still applies and still says a source set it. Only the identity is withheld.
        self.assertEqual(bounds["floor"]["label"], "6 hours")
        self.assertIsNone(bounds["floor"]["blocker"])
        blocked = {option["cadence"]: option for option in bounds["options"] if not option["allowed"]}
        self.assertEqual(blocked["15min"]["blocked_by"], "source")
        self.assertIsNone(blocked["15min"]["blocker"])
        self.assertNotIn("stripe_charges", body)


@pytest.mark.ee
class TestSyncFrequencyDuplicateResourceAcrossDags(WarehouseAccessControlTestMixin):
    """A grant covers a resource, not a node: a table holding a node in two DAGs is named in both."""

    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="downstream_view",
            query={"kind": "HogQLQuery", "query": "select 1 as event"},
            created_by=self.user,
        )
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="posthog_test_",
        )
        # Deliberately no schema: a source with no sync schedule is what lands in best-effort, and
        # best-effort ids union across DAGs. That union is the one place a single resource reaches
        # the payload under two node ids.
        self.table = DataWarehouseTable.objects.create(
            name="unscheduled_source", team=self.team, external_data_source=self.source
        )
        for dag_name in ("dag_one", "dag_two"):
            dag = DAG.objects.create(team=self.team, name=dag_name)
            source_node = Node.objects.create(
                team=self.team,
                dag=dag,
                name="unscheduled_source",
                type=NodeType.TABLE,
                properties={"origin": "warehouse", "warehouse_table_id": str(self.table.id)},
            )
            view_node = Node.objects.create(
                team=self.team, dag=dag, name=self.view.name, saved_query=self.view, type=NodeType.VIEW
            )
            Edge.objects.create(team=self.team, dag=dag, source=source_node, target=view_node)

    def _read_view(self) -> dict:
        with (
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == "data-modeling-backend-v2",
            ),
            patch(
                "products.data_modeling.backend.logic.schedule_reconcile.tiered_schedules_enabled",
                return_value=True,
            ),
        ):
            response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.view.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()["sync_frequency_bounds"]

    def test_a_readable_table_is_named_through_every_dag_that_holds_a_node_for_it(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        bounds = self._read_view()

        self.assertTrue(bounds["best_effort_sources"], "the unscheduled source should reach the payload")
        self.assertTrue(all(source["name"] == "unscheduled_source" for source in bounds["best_effort_sources"]))
        # The caller may read the only table involved, so nothing is cut and the copy says so.
        self.assertFalse(bounds["best_effort_sources_withheld"])

    def test_a_denied_table_stays_withheld_through_every_dag(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(
            self.viewer_user, resource="warehouse_table", resource_id=str(self.table.id), access_level="none"
        )
        self.client.force_login(self.viewer_user)

        bounds = self._read_view()

        self.assertTrue(bounds["best_effort_sources_withheld"])
        self.assertEqual(bounds["best_effort_sources"], [])
