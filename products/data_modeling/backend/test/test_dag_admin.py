from datetime import timedelta

from posthog.test.base import BaseTest

from django.contrib import admin
from django.test import override_settings
from django.urls import reverse

from posthog.admin import register_all_admin

from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.data_modeling_job import DataModelingJob, DataModelingJobStatus
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.test.helpers import saved_query_node

# `posthog/apps.py` installs the lazy admin registry only `if not settings.TEST`, and that wrapper
# is the sole caller of `register_all_admin()` — so under tests nothing ever registers a
# product-local admin. (Autodiscovery itself is fine: this module is exactly what
# `autodiscover_modules("admin")` imports for this app in a real process.)
register_all_admin()


@override_settings(TEMPORAL_UI_HOST="https://temporal.example.com", TEMPORAL_NAMESPACE="prod")
class TestDataModelingDAGAdminTiers(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True  # is_superuser is a read-only alias for is_staff
        self.user.save()
        self.client.force_login(self.user)
        self.dag = DAG.objects.create(team=self.team, name="Default")

    def _node(self, name: str, target: timedelta | None) -> Node:
        node = saved_query_node(self.team, self.dag, name, NodeType.MAT_VIEW)
        if target is not None:
            set_declared_target(node, target)
            node.save()
        return node

    def test_the_admin_is_registered_through_the_real_registration_path(self):
        # importing this module would also register it, but that would hide a duplicate
        # registration elsewhere — which raises AlreadyRegistered and takes the whole admin down
        assert admin.site.is_registered(DAG)

    def test_tiers_page_renders_each_tier_with_temporal_links(self):
        node = self._node("daily_model", timedelta(days=1))
        self._node("hourly_model", timedelta(hours=1))
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=node.saved_query,
            status=DataModelingJobStatus.COMPLETED,
            parent_workflow_id=f"execute-dag-{self.dag.id}:86400-2026-07-25T03:00:00Z",
            workflow_id="materialize-view-child",
            workflow_run_id="run-1",
        )

        response = self.client.get(reverse("admin:data_modeling_dag_tiers", args=[self.dag.id]))
        content = response.content.decode()

        assert response.status_code == 200
        assert "daily_model" in content
        assert "1day" in content
        # the summary table resolves counts through a dict lookup, which Django renders as "" on a
        # miss rather than raising — so a renamed status constant would silently blank it
        assert 'id="tier-86400"' in content and 'id="tier-3600"' in content
        assert f"https://temporal.example.com/namespaces/prod/schedules/execute-dag-{self.dag.id}:86400" in content
        assert "https://temporal.example.com/namespaces/prod/workflows/materialize-view-child/run-1" in content

    def test_tiers_page_renders_for_a_dag_with_no_targets(self):
        self._node("untargeted_model", None)

        response = self.client.get(reverse("admin:data_modeling_dag_tiers", args=[self.dag.id]))
        content = response.content.decode()

        assert response.status_code == 200
        assert "has no tiers" in content
        assert "untargeted_model" in content

    def test_an_unknown_dag_id_is_a_404_not_a_crash(self):
        response = self.client.get(
            reverse("admin:data_modeling_dag_tiers", args=["019f98c1-0000-0000-0000-000000000000"])
        )

        assert response.status_code == 404

    def test_changelist_and_add_form_render(self):
        # both call into the display helpers that reverse other admin URLs, and the add form is the
        # only caller of tiers_link with an unsaved object
        assert self.client.get(reverse("admin:data_modeling_dag_changelist")).status_code == 200
        assert self.client.get(reverse("admin:data_modeling_dag_add")).status_code == 200

    def test_tiers_page_requires_staff(self):
        self.user.is_staff = False
        self.user.save()

        response = self.client.get(reverse("admin:data_modeling_dag_tiers", args=[self.dag.id]))

        assert response.status_code == 302
        assert "/admin/login/" in response["Location"]
