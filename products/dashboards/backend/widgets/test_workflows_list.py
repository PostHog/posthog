from datetime import UTC, datetime

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.dashboards.backend.widget_specs.registry import get_widget_registry_entry, validate_widget_config
from products.workflows.backend.facade.contracts import WorkflowActivityPage, WorkflowActivityRow

BASE_ROW = WorkflowActivityRow(
    id="flow-1",
    name="Welcome",
    description="",
    status="active",
    workflow_type="messaging",
    trigger_type="event",
    has_email_step=True,
    updated_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    started=5,
    completed=3,
    failed=1,
    email_sent=3,
    email_delivered=3,
    email_opened=2,
    email_bounced=0,
)


@time_machine.travel("2026-08-10 12:00:00", tick=False)
class TestWorkflowsListWidget(BaseTest):
    def test_rejects_unknown_status_and_type(self) -> None:
        with self.assertRaises(Exception):
            validate_widget_config("workflows_list", {"status": "paused"})
        with self.assertRaises(Exception):
            validate_widget_config("workflows_list", {"workflowType": "email"})

    def test_maps_config_to_facade_and_serializes_rows(self) -> None:
        entry = get_widget_registry_entry("workflows_list")
        assert entry is not None
        with patch(
            "products.dashboards.backend.widgets.workflows_list.list_workflow_activity",
            return_value=WorkflowActivityPage(rows=(BASE_ROW,), has_more=True),
        ) as facade:
            result = entry["query_fn"](
                self.team,
                {"limit": 5, "status": "all", "workflowType": "broadcast", "dateRange": {"date_from": "-24h"}},
                self.user,
            )

        kwargs = facade.call_args.kwargs
        assert kwargs["status"] is None
        assert kwargs["workflow_type"] == "broadcast"
        assert kwargs["limit"] == 5
        assert kwargs["after"] == datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
        assert kwargs["before"] == datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
        assert kwargs["access_control"] is not None
        assert result["hasMore"] is True
        assert "totalCount" not in result
        assert result["results"][0]["id"] == "flow-1"
        assert result["results"][0]["started"] == 5
        assert result["results"][0]["email_opened"] == 2
        assert result["results"][0]["updated_at"] == "2026-08-09T12:00:00+00:00"

    def test_defaults_to_active_workflows_over_the_last_week(self) -> None:
        entry = get_widget_registry_entry("workflows_list")
        assert entry is not None
        with patch(
            "products.dashboards.backend.widgets.workflows_list.list_workflow_activity",
            return_value=WorkflowActivityPage(rows=(), has_more=False),
        ) as facade:
            result = entry["query_fn"](self.team, {}, None)

        kwargs = facade.call_args.kwargs
        assert kwargs["status"] == "active"
        assert kwargs["workflow_type"] is None
        assert kwargs["after"] == datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
        assert kwargs["access_control"] is None
        assert result == {
            "results": [],
            "hasMore": False,
            "limit": 10,
            "offset": 0,
            "totalCount": 0,
            "totalCountCapped": False,
        }
