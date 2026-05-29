from typing import cast

from django.test import TestCase

from posthog.models.activity_logging.activity_log import AuditableScope, Change, describe_change, dict_changes_between

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


class TeatActivityLog(TestCase):
    def test_dict_changes_between(self):
        changes = dict_changes_between(
            model_type="Plugin",
            previous={"change_field": "foo", "delete_field": "foo"},
            new={"change_field": "bar", "new_field": "bar"},
        )

        self.assertEqual(len(changes), 3)

        self.assertIn(
            Change(
                type="Plugin",
                action="changed",
                field="change_field",
                before="foo",
                after="bar",
            ),
            changes,
        )
        self.assertIn(
            Change(
                type="Plugin",
                action="created",
                field="new_field",
                before=None,
                after="bar",
            ),
            changes,
        )
        self.assertIn(
            Change(
                type="Plugin",
                action="deleted",
                field="delete_field",
                before="foo",
                after=None,
            ),
            changes,
        )

    def test_dashboard_tile_describe_change_includes_absent_content_keys(self):
        tile = DashboardTile(insight_id=1, widget_id=None, button_tile_id=None, text_id=None)
        tile.dashboard = Dashboard(id=2, name="Dash")

        description = describe_change(tile)

        self.assertEqual(
            description,
            {
                "dashboard": {"id": 2, "name": "Dash"},
                "insight": {"id": 1},
                "text": None,
                "button_tile": None,
                "widget": None,
            },
        )

    def test_dict_changes_between_ignores_new_null_tile_content_keys(self):
        previous = {"dashboard": {"id": 1, "name": "Dash"}, "insight": {"id": 10}}
        new = {
            "dashboard": {"id": 1, "name": "Dash"},
            "insight": {"id": 10},
            "text": None,
            "button_tile": None,
            "widget": None,
        }

        self.assertEqual(dict_changes_between(cast(AuditableScope, "DashboardTile"), previous, new), [])
