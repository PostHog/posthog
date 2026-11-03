from datetime import timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from parameterized import parameterized

from products.data_modeling.backend.logic.node_suspension import is_node_suspended, mark_node_suspended
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import Node


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestClearNodeSuspensionsAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.url = reverse("admin:data_modeling_clear_node_suspensions")
        self.dag = DAG.objects.create(team=self.team, name="Admin test")

    def _node(self, reason: str = "TEST_QUERY_LIMIT", engine: str = "clickhouse") -> Node:
        node = Node.objects.create(team=self.team, dag=self.dag, name=f"test_{uuid4().hex}")
        mark_node_suspended(node, engine=engine, reason=reason, job_id=str(uuid4()))
        node.save()
        return node

    @parameterized.expand([("default_actor", ""), ("operator_note", "Retry after the query limit was restored.")])
    def test_preview_and_clear_only_reviewed_markers(self, _name: str, note: str) -> None:
        selected = self._node()
        mark_node_suspended(selected, engine="managed_warehouse", reason="TEST_QUERY_LIMIT", job_id=str(uuid4()))
        selected.save()
        unrelated = self._node(reason="TEST_INVALID_COLUMN")
        old = self._node()
        old.properties["system"]["suspended"]["clickhouse"]["at"] = (timezone.now() - timedelta(days=2)).isoformat()
        old.save()

        response = self.client.post(
            self.url,
            {
                "engine": "clickhouse",
                "reason_contains": "TEST_QUERY_LIMIT\nTEST_OTHER_LIMIT",
                "team_id": self.team.pk,
                "suspended_from": (timezone.now() - timedelta(days=1)).isoformat(),
                "by": note,
            },
        )

        assert response.status_code == 200
        assert [marker.node.pk for marker in response.context["markers"]] == [selected.pk]
        expected_by = note or f"admin:{self.user.pk}"
        assert response.context["resumed_by"] == expected_by
        selected.refresh_from_db()
        assert is_node_suspended(selected, "clickhouse")
        new = self._node()

        result = self.client.post(
            self.url,
            {"action": "clear", "preview_token": response.context["preview_token"], "by": "Unreviewed note"},
        )

        assert result.status_code == 302
        selected.refresh_from_db()
        assert not is_node_suspended(selected, "clickhouse")
        assert is_node_suspended(selected, "managed_warehouse")
        assert selected.properties["system"]["suspension_reset"]["clickhouse"]["by"] == expected_by
        log = LogEntry.objects.get(user=self.user, object_id=str(selected.pk))
        assert expected_by in log.change_message
        for node in (unrelated, old, new):
            node.refresh_from_db()
            assert is_node_suspended(node, "clickhouse")

        replay = self.client.post(self.url, {"action": "clear", "preview_token": response.context["preview_token"]})
        assert replay.status_code == 302
        assert LogEntry.objects.filter(user=self.user, object_id=str(selected.pk)).count() == 1

    def test_preserves_newer_suspension_after_preview(self) -> None:
        node = self._node()
        preview = self.client.post(self.url, {"engine": "clickhouse", "node_ids": str(node.pk)})
        mark_node_suspended(node, engine="clickhouse", reason="TEST_NEW_FAILURE", job_id=str(uuid4()))
        node.save()

        self.client.post(self.url, {"action": "clear", "preview_token": preview.context["preview_token"]})

        node.refresh_from_db()
        assert is_node_suspended(node, "clickhouse")
        assert not LogEntry.objects.filter(object_id=str(node.pk)).exists()

    def test_failed_audit_entry_rolls_back_the_reset(self) -> None:
        node = self._node()
        preview = self.client.post(self.url, {"engine": "clickhouse", "node_ids": str(node.pk)})

        with patch(
            "products.data_modeling.backend.admin.DataModelingDAGAdmin.log_change", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, {"action": "clear", "preview_token": preview.context["preview_token"]})

        node.refresh_from_db()
        assert is_node_suspended(node, "clickhouse")

    @parameterized.expand(
        [
            ({"engine": "clickhouse"}, "Enter error text"),
            ({"reason_contains": "   \n  "}, "Enter error text"),
            ({"node_ids": "invalid"}, "Enter valid comma-separated UUIDs"),
            (
                {
                    "reason_contains": "TEST",
                    "suspended_from": "2026-10-02T00:00:00Z",
                    "suspended_to": "2026-10-01T00:00:00Z",
                },
                "Suspended to must be after suspended from",
            ),
        ]
    )
    def test_invalid_selection_cannot_clear(self, data: dict, error: str) -> None:
        node = self._node()
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        assert error in response.content.decode()
        assert not response.context["preview_token"]
        self.client.post(self.url, {"action": "clear", "preview_token": "invalid"})
        node.refresh_from_db()
        assert is_node_suspended(node, "clickhouse")

    @parameterized.expand([("get",), ("post",)])
    def test_requires_staff_access(self, method: str) -> None:
        self.user.is_staff = False
        self.user.save()
        response = getattr(self.client, method)(self.url)
        assert response.status_code == 302
        assert "/admin/login/" in response.url

    def test_preview_limit_requires_narrower_filters(self) -> None:
        self._node()
        self._node()
        with patch("products.data_modeling.backend.forms.MAX_SUSPENSION_PREVIEW", 1):
            response = self.client.post(self.url, {"reason_contains": "TEST_QUERY_LIMIT"})
        assert "Add filters and preview again" in response.content.decode()
        assert not response.context["preview_token"]

    def test_preview_escapes_error_text_and_has_admin_entry_point(self) -> None:
        self._node(reason="<script>alert('test')</script>")
        response = self.client.post(self.url, {"reason_contains": "<script>"})
        assert "&lt;script&gt;" in response.content.decode()
        assert "<script>alert('test')</script>" not in response.content.decode()
        changelist = self.client.get(reverse("admin:data_modeling_dag_changelist"))
        assert self.url in changelist.content.decode()
