import pytest
from posthog.test.base import BaseTest

from rest_framework import exceptions

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.revert import apply_revert_to_instance, lookup_revertable_activity_log_entry

from products.dashboards.backend.models.dashboard import Dashboard


class TestLookupRevertableActivityLogEntry(BaseTest):
    def _create_log_entry(self, *, team_id: int, organization_id, scope: str, item_id: str) -> ActivityLog:
        return ActivityLog.objects.create(
            team_id=team_id,
            organization_id=organization_id,
            user=self.user,
            scope=scope,
            item_id=item_id,
            activity="updated",
            detail={
                "name": "Dashboard",
                "type": "dashboard",
                "changes": [{"type": "Dashboard", "action": "changed", "field": "name", "before": "A", "after": "B"}],
            },
        )

    def test_returns_matching_entry(self):
        entry = self._create_log_entry(
            team_id=self.team.id, organization_id=self.organization.id, scope="Dashboard", item_id="42"
        )
        result = lookup_revertable_activity_log_entry(
            activity_log_id=entry.id,
            scope="Dashboard",
            item_id="42",
            team_id=self.team.id,
            organization_id=self.organization.id,
            include_org_scoped=False,
            user=self.user,
        )
        assert result.id == entry.id

    def test_raises_not_found_when_scope_mismatch(self):
        entry = self._create_log_entry(
            team_id=self.team.id, organization_id=self.organization.id, scope="Dashboard", item_id="42"
        )
        with pytest.raises(exceptions.NotFound):
            lookup_revertable_activity_log_entry(
                activity_log_id=entry.id,
                scope="Insight",
                item_id="42",
                team_id=self.team.id,
                organization_id=self.organization.id,
                include_org_scoped=False,
                user=self.user,
            )

    def test_raises_not_found_when_item_id_mismatch(self):
        entry = self._create_log_entry(
            team_id=self.team.id, organization_id=self.organization.id, scope="Dashboard", item_id="42"
        )
        with pytest.raises(exceptions.NotFound):
            lookup_revertable_activity_log_entry(
                activity_log_id=entry.id,
                scope="Dashboard",
                item_id="99",
                team_id=self.team.id,
                organization_id=self.organization.id,
                include_org_scoped=False,
                user=self.user,
            )

    def test_raises_not_found_when_team_mismatch(self):
        other_org = self.organization.__class__.objects.create(name="Other Org")
        from posthog.models import Team

        other_team = Team.objects.create(organization=other_org, name="Other Team")
        entry = self._create_log_entry(
            team_id=other_team.id, organization_id=other_org.id, scope="Dashboard", item_id="42"
        )
        with pytest.raises(exceptions.NotFound):
            lookup_revertable_activity_log_entry(
                activity_log_id=entry.id,
                scope="Dashboard",
                item_id="42",
                team_id=self.team.id,
                organization_id=self.organization.id,
                include_org_scoped=False,
                user=self.user,
            )

    def _create_log_with_changes(self, item_id: str, changes: list[dict]) -> ActivityLog:
        return ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            user=self.user,
            scope="Dashboard",
            item_id=item_id,
            activity="updated",
            detail={"name": "D", "type": "dashboard", "changes": changes},
        )

    def test_fallback_returns_most_recent_revertable_entry(self):
        # An older revertable entry followed by a newer revertable entry — the newer one wins.
        self._create_log_with_changes(
            "42",
            [{"type": "Dashboard", "action": "changed", "field": "name", "before": "old", "after": "new"}],
        )
        newer = self._create_log_with_changes(
            "42",
            [
                {
                    "type": "Dashboard",
                    "action": "changed",
                    "field": "description",
                    "before": "old desc",
                    "after": "new desc",
                }
            ],
        )
        result = lookup_revertable_activity_log_entry(
            activity_log_id=None,
            scope="Dashboard",
            item_id="42",
            team_id=self.team.id,
            organization_id=self.organization.id,
            include_org_scoped=False,
            user=self.user,
            revertable_fields={"name", "description"},
        )
        assert result.id == newer.id

    def test_fallback_skips_non_revertable_entries(self):
        # Newest entry only touches a non-revertable field; the previous one is returned.
        older = self._create_log_with_changes(
            "42",
            [{"type": "Dashboard", "action": "changed", "field": "name", "before": "old", "after": "new"}],
        )
        self._create_log_with_changes(
            "42",
            [{"type": "Dashboard", "action": "changed", "field": "created_by", "before": None, "after": 1}],
        )
        result = lookup_revertable_activity_log_entry(
            activity_log_id=None,
            scope="Dashboard",
            item_id="42",
            team_id=self.team.id,
            organization_id=self.organization.id,
            include_org_scoped=False,
            user=self.user,
            revertable_fields={"name"},
        )
        assert result.id == older.id

    def test_fallback_raises_not_found_when_no_revertable_entry(self):
        self._create_log_with_changes(
            "42",
            [{"type": "Dashboard", "action": "changed", "field": "created_by", "before": None, "after": 1}],
        )
        with pytest.raises(exceptions.NotFound):
            lookup_revertable_activity_log_entry(
                activity_log_id=None,
                scope="Dashboard",
                item_id="42",
                team_id=self.team.id,
                organization_id=self.organization.id,
                include_org_scoped=False,
                user=self.user,
                revertable_fields={"name"},
            )

    def test_fallback_requires_revertable_fields(self):
        with pytest.raises(exceptions.ValidationError):
            lookup_revertable_activity_log_entry(
                activity_log_id=None,
                scope="Dashboard",
                item_id="42",
                team_id=self.team.id,
                organization_id=self.organization.id,
                include_org_scoped=False,
                user=self.user,
                revertable_fields=None,
            )


class TestApplyRevertToInstance(BaseTest):
    def _log_entry_with_changes(self, changes: list[dict]) -> ActivityLog:
        return ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            user=self.user,
            scope="Dashboard",
            item_id="1",
            activity="updated",
            detail={"name": "Dashboard", "type": "dashboard", "changes": changes},
        )

    def test_applies_revertable_field_and_skips_others(self):
        dashboard = Dashboard.objects.create(team=self.team, name="Edited", description="Edited description")
        entry = self._log_entry_with_changes(
            [
                {"type": "Dashboard", "action": "changed", "field": "name", "before": "Original", "after": "Edited"},
                {"type": "Dashboard", "action": "changed", "field": "created_by", "before": None, "after": 1},
            ]
        )
        applied, skipped = apply_revert_to_instance(dashboard, entry, {"name"})
        assert applied == ["name"]
        assert skipped == ["created_by"]
        assert dashboard.name == "Original"
        # The caller is responsible for save() — instance is mutated in place but not persisted.
        dashboard.refresh_from_db()
        assert dashboard.name == "Edited"

    def test_raises_validation_error_when_no_changes(self):
        dashboard = Dashboard.objects.create(team=self.team, name="D")
        entry = self._log_entry_with_changes([])
        with pytest.raises(exceptions.ValidationError):
            apply_revert_to_instance(dashboard, entry, {"name"})

    def test_raises_validation_error_when_all_skipped(self):
        dashboard = Dashboard.objects.create(team=self.team, name="D")
        entry = self._log_entry_with_changes(
            [{"type": "Dashboard", "action": "changed", "field": "created_by", "before": None, "after": 1}]
        )
        with pytest.raises(exceptions.ValidationError):
            apply_revert_to_instance(dashboard, entry, {"name"})

    def test_change_missing_field_is_ignored(self):
        dashboard = Dashboard.objects.create(team=self.team, name="Edited")
        entry = self._log_entry_with_changes(
            [
                {"type": "Dashboard", "action": "changed", "field": None, "before": "x", "after": "y"},
                {"type": "Dashboard", "action": "changed", "field": "name", "before": "Original", "after": "Edited"},
            ]
        )
        applied, skipped = apply_revert_to_instance(dashboard, entry, {"name"})
        assert applied == ["name"]
        assert skipped == []
        assert dashboard.name == "Original"
