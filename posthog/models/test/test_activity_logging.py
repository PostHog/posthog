from typing import cast

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    AuditableScope,
    Change,
    describe_change,
    dict_changes_between,
    get_activity_page,
)
from posthog.models.activity_logging.activity_page import ActivityPaginationParamsSerializer

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


class TestGetActivityPage(TestCase):
    def _make_logs(self, count: int) -> None:
        ActivityLog.objects.bulk_create(
            ActivityLog(team_id=424242, scope="Insight", activity="updated", item_id=str(i)) for i in range(count)
        )

    def test_page_past_the_end_returns_empty_terminator_not_error(self) -> None:
        self._make_logs(3)
        query = ActivityLog.objects.filter(team_id=424242, scope="Insight").order_by("item_id")

        page = get_activity_page(query, limit=10, page=99)

        self.assertEqual(page.results, [])
        self.assertEqual(page.total_count, 3)
        self.assertFalse(page.has_next)
        self.assertTrue(page.has_previous)

    def test_valid_last_page_still_returns_its_rows(self) -> None:
        self._make_logs(15)
        query = ActivityLog.objects.filter(team_id=424242, scope="Insight").order_by("item_id")

        page = get_activity_page(query, limit=10, page=2)

        self.assertEqual(len(page.results), 5)
        self.assertEqual(page.total_count, 15)
        self.assertFalse(page.has_next)
        self.assertTrue(page.has_previous)


class TestActivityPaginationParamsSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("non_numeric_page", {"page": "abc"}, "page"),
            ("non_numeric_limit", {"limit": "abc"}, "limit"),
            ("zero_limit", {"limit": "0"}, "limit"),
            ("negative_page", {"page": "-1"}, "page"),
        ]
    )
    def test_rejects_invalid_param(self, _name: str, data: dict, field: str) -> None:
        serializer = ActivityPaginationParamsSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    def test_applies_defaults_when_absent(self) -> None:
        serializer = ActivityPaginationParamsSerializer(data={})

        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["limit"], 10)
        self.assertEqual(serializer.validated_data["page"], 1)
