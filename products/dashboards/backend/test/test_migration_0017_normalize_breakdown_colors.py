import json
from typing import Any

from posthog.test.base import TestMigrations

from django.db import connection

_CHROME = {"breakdownValue": "Chrome", "colorToken": "preset-1"}
_FIREFOX = {"breakdownValue": "Firefox", "colorToken": "preset-2"}

# Stored value, then what the migration must leave behind. Every shape in one row set, because the
# risk is the SQL expanding a row it should skip rather than any single shape: jsonb_array_elements
# raises on a scalar, which fails the whole migration instead of passing over the row.
_CASES: list[tuple[str, Any, Any]] = [
    ("object_keyed_by_breakdown_value", {"Chrome": "preset-1"}, []),
    ("empty_object", {}, []),
    ("json_encoded_list", '[{"breakdownValue": "Chrome", "colorToken": "preset-1"}]', []),
    ("bare_breakdown_values", ["Chrome", "Firefox"], []),
    ("null_entry", [None], []),
    ("nested_list_entry", [["Chrome", "preset-1"]], []),
    ("entry_under_snake_case_keys", [{"breakdown_value": "good", "color": "#36a854"}], []),
    ("entry_missing_the_color_token", [{"breakdownValue": "Chrome"}], []),
    ("entry_with_a_hex_color_token", [{"breakdownValue": "Chrome", "colorToken": "#3fb950"}], []),
    # Order has to survive, because a dashboard save diffs the color list against what is persisted.
    (
        "mixed_entries_keep_their_order",
        [_FIREFOX, {"breakdownValue": "a", "colorToken": "#3fb950"}, _CHROME],
        [_FIREFOX, _CHROME],
    ),
    # A key the migration does not know about is not a reason to drop the entry, so a color saved by
    # a later frontend survives a backfill that predates it.
    (
        "entry_with_an_unknown_key",
        [{**_CHROME, "somethingAddedLater": "kept"}],
        [{**_CHROME, "somethingAddedLater": "kept"}],
    ),
    # A cleared color is stored as an entry with a null token, which is not a broken entry.
    (
        "null_color_token",
        [{"breakdownValue": "Chrome", "colorToken": None}],
        [{"breakdownValue": "Chrome", "colorToken": None}],
    ),
    (
        "every_key",
        [{**_CHROME, "breakdownType": "event", "breakdownProperty": "event::$browser", "source": "manual"}],
        [{**_CHROME, "breakdownType": "event", "breakdownProperty": "event::$browser", "source": "manual"}],
    ),
    ("already_empty", [], []),
    ("never_set", None, None),
]

# Most rows that need a fix are soft-deleted, so the statement must not skip them.
_DELETED_CASE: tuple[str, Any, Any] = ("soft_deleted_object", {"Chrome": "preset-1"}, [])


class NormalizeDashboardBreakdownColorsMigrationTest(TestMigrations):
    migrate_from = "0016_dashboardsavedview"
    migrate_to = "0017_normalize_dashboard_breakdown_colors"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "dashboards"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        Dashboard = apps.get_model("dashboards", "Dashboard")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=999993, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")

        self.dashboard_ids: dict[str, int] = {}
        for label, stored, _expected in [*_CASES, _DELETED_CASE]:
            dashboard = Dashboard.objects.create(
                team=team,
                name=label,
                breakdown_colors=stored,
                deleted=label == _DELETED_CASE[0],
            )
            self.dashboard_ids[label] = dashboard.id

    def test_keeps_only_the_entries_a_dashboard_can_use(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, breakdown_colors FROM posthog_dashboard WHERE id = ANY(%s)",
                [list(self.dashboard_ids.values())],
            )
            # A raw cursor hands back the jsonb column as text, because it bypasses the decoding
            # Django's JSONField would do.
            stored_by_id = {
                id: json.loads(value) if isinstance(value, str) else value for id, value in cursor.fetchall()
            }

        actual = {label: stored_by_id[id] for label, id in self.dashboard_ids.items()}
        expected = {label: expected for label, _stored, expected in [*_CASES, _DELETED_CASE]}

        assert actual == expected
