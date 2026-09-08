from io import StringIO
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.management.commands.clear_unusable_breakdown_colors import (
    clear_unusable_breakdown_colors,
    clear_unusable_entries,
)
from products.dashboards.backend.models.dashboard import Dashboard

_CHROME = {"breakdownValue": "Chrome", "colorToken": "preset-1"}
_FIREFOX = {"breakdownValue": "Firefox", "colorToken": "preset-2"}


class TestClearUnusableEntries(SimpleTestCase):
    @parameterized.expand(
        [
            # The two shapes that give every viewer an error screen instead of tiles.
            ("object_keyed_by_breakdown_value", {"Chrome": "preset-1"}, []),
            ("empty_object", {}, []),
            ("json_encoded_list", '[{"breakdownValue": "Chrome", "colorToken": "preset-1"}]', []),
            ("bare_breakdown_values", ["Chrome", "Firefox"], []),
            ("null_entry", [None], []),
            ("nested_list_entry", [["Chrome", "preset-1"]], []),
            ("entry_under_snake_case_keys", [{"breakdown_value": "good", "color": "#36a854"}], []),
            ("entry_missing_the_color_token", [{"breakdownValue": "Chrome"}], []),
            ("entry_with_a_hex_color_token", [{"breakdownValue": "Chrome", "colorToken": "#3fb950"}], []),
            # A token that is not a string at all reaches the pattern match, which raises on it and
            # would take down the whole run rather than skip the entry.
            ("entry_with_a_numeric_color_token", [{"breakdownValue": "Chrome", "colorToken": 1}], []),
            # Order has to survive, because a dashboard save diffs the color list against what is
            # persisted.
            (
                "mixed_entries_keep_their_order",
                [_FIREFOX, {"breakdownValue": "a", "colorToken": "#3fb950"}, _CHROME],
                [_FIREFOX, _CHROME],
            ),
            # A key this command does not declare is not a reason to drop the entry, so a color
            # saved by a later frontend survives a run that predates it.
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
    )
    def test_keeps_only_the_entries_a_dashboard_can_use(self, _name: str, stored: Any, expected: Any) -> None:
        assert clear_unusable_entries(stored) == expected


class TestClearUnusableBreakdownColorsCommand(BaseTest):
    def _dashboard(self, name: str, breakdown_colors: Any, deleted: bool = False) -> Dashboard:
        return Dashboard.objects.create(team=self.team, name=name, breakdown_colors=breakdown_colors, deleted=deleted)

    def _run(self, *args: str) -> str:
        stdout = StringIO()
        call_command(
            "clear_unusable_breakdown_colors",
            "--sleep-interval=0",
            f"--team-id={self.team.id}",
            *args,
            stdout=stdout,
        )
        return stdout.getvalue()

    def _stored(self, dashboard: Dashboard) -> Any:
        return Dashboard.objects_including_soft_deleted.values_list("breakdown_colors", flat=True).get(id=dashboard.id)

    @parameterized.expand(
        [
            # A stored object is the shape that breaks the scene, and it also pins the value lookup
            # the write filters on: matching a jsonb object against the value just read.
            ("object_keyed_by_breakdown_value", {"Chrome": "preset-1"}, []),
            (
                "mixed_entries",
                [_FIREFOX, {"breakdownValue": "a", "colorToken": "#3fb950"}, _CHROME],
                [_FIREFOX, _CHROME],
            ),
        ]
    )
    def test_live_run_persists_the_cleared_value(self, _name: str, stored: Any, expected: Any) -> None:
        dashboard = self._dashboard("Affected", stored)

        self._run("--live-run")

        assert self._stored(dashboard) == expected

    def test_live_run_reaches_a_soft_deleted_dashboard(self) -> None:
        # The default manager hides soft-deleted rows, and a soft-deleted dashboard can be restored,
        # so reading through it would leave the crash in place for anyone who restores one.
        dashboard = self._dashboard("Deleted", {"Chrome": "preset-1"}, deleted=True)

        self._run("--live-run")

        assert self._stored(dashboard) == []

    def test_leaves_a_dashboard_whose_colors_all_apply(self) -> None:
        # A row needing no change must be skipped before the write, not rewritten with the same
        # value. Rewriting every row would also report every dashboard as changed, which buries the
        # rows an operator has to read.
        dashboard = self._dashboard("Fine", [_CHROME, _FIREFOX])

        output = self._run("--live-run")

        assert self._stored(dashboard) == [_CHROME, _FIREFOX]
        assert f"dashboard {dashboard.id}" not in output

    def test_dashboard_id_scopes_the_run_to_that_dashboard(self) -> None:
        # An operator repairing one dashboard must not clear the rest of the team's. A filter on the
        # wrong field would widen a targeted run into a team-wide one.
        target = self._dashboard("Target", {"Chrome": "preset-1"})
        other = self._dashboard("Other", {"Firefox": "preset-2"})

        self._run("--live-run", f"--dashboard-id={target.id}")

        assert self._stored(target) == []
        assert self._stored(other) == {"Firefox": "preset-2"}

    def test_dry_run_reports_the_change_without_writing(self) -> None:
        dashboard = self._dashboard("Affected", {"Chrome": "preset-1"})

        output = self._run()

        assert self._stored(dashboard) == {"Chrome": "preset-1"}
        assert f"dashboard {dashboard.id}" in output
        assert "would_change=1" in output

    def test_leaves_a_dashboard_whose_value_changed_since_it_was_read(self) -> None:
        # Entries are read in batches and written one row at a time, so a save can land in between.
        # The write filters on the value it read, which is what keeps that save from being
        # overwritten by a value read before it.
        first = self._dashboard("First", {"Chrome": "preset-1"})
        second = self._dashboard("Second", {"Firefox": "preset-2"})

        changes = clear_unusable_breakdown_colors(live_run=True, team_id=self.team.id, batch_size=2)
        assert next(changes).dashboard_id == first.id
        Dashboard.objects.filter(id=second.id).update(breakdown_colors=[_CHROME])

        assert next(changes).outcome == "concurrent_save"
        assert self._stored(second) == [_CHROME]
