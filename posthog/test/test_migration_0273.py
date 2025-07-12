import importlib
import json
from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.utils import timezone
from freezegun.api import freeze_time

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization
from posthog.models.plugin import Plugin, PluginConfig, PluginStorage
from posthog.models.team.team import Team

import pytest

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


@freeze_time("2021-08-25T13:00:00Z")
class MarkInactiveExportsAsFinished(TestCase):
    """
    Test that the migration 0273_mark_inactive_exports_as_finished.py works as
    expected. It should update th activity log entries for exports such that any
    failed exports are highlighted as such.

    NOTE: this test used to explicitly test the migration by first migrating to
    migration 0272 and then migrating to 0273. However, this is not possible
    with the addition of a squashed migration from posthog 0001 to 0284, as the
    migration in question is not elided. Instead, we explicitly test the
    migration forwards code. This isn't ideal as we're not testing with the same
    model state as the migration would be run on, but it's better than nothing.
    """

    def test_migration(self):
        # First we go back to the previous migration, and setup the database
        # state with exports in various states.

        self.organization = Organization.objects.create()
        self.team = Team.objects.create(organization=self.organization, app_urls=[])
        self.plugins = [Plugin.objects.create(organization_id=self.organization.pk) for _ in range(6)]
        self.plugin_configs = [
            PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=i)
            for i, plugin in enumerate(self.plugins)
        ]

        # Case 1: Old non-finished export
        self.create_entry(
            self.plugin_configs[0].pk,
            created_at=timezone.now() - timedelta(days=1),
            activity="job_triggered",
            detail={
                "trigger": {
                    "job_id": "1",
                    "job_type": "Export historical events V2",
                    "payload": {},
                }
            },
        )

        # Case 2: Finished export
        self.create_entry(
            self.plugin_configs[1].pk,
            created_at=timezone.now() - timedelta(days=1),
            activity="job_triggered",
            detail={
                "trigger": {
                    "job_id": "2",
                    "job_type": "Export historical events V2",
                    "payload": {},
                }
            },
        )
        self.create_entry(
            self.plugin_configs[1].pk,
            created_at=timezone.now() - timedelta(days=1),
            activity="export_success",
            detail={
                "trigger": {
                    "job_id": "2",
                    "job_type": "Export historical events V2",
                    "payload": {},
                }
            },
        )

        # Case 3: Failed export
        self.create_entry(
            self.plugin_configs[2].pk,
            created_at=timezone.now() - timedelta(days=1),
            activity="job_triggered",
            detail={
                "trigger": {
                    "job_id": "3",
                    "job_type": "Export historical events V2",
                    "payload": {},
                }
            },
        )
        self.create_entry(
            self.plugin_configs[2].pk,
            created_at=timezone.now() - timedelta(days=1),
            activity="export_fail",
            detail={
                "trigger": {
                    "job_id": "3",
                    "job_type": "Export historical events V2",
                    "payload": {},
                    "failure_reason": "Some reason",
                }
            },
        )

        # Case 4: Recently started export
        self.create_entry(
            self.plugin_configs[3].pk,
            created_at=timezone.now() - timedelta(minutes=2),
            activity="job_triggered",
            detail={
                "trigger": {
                    "job_id": "4",
                    "job_type": "Export historical events V2",
                    "payload": {},
                }
            },
        )

        # Case 5: Started export with storage containing it's running
        self.create_entry(
            self.plugin_configs[4].pk,
            created_at=timezone.now() - timedelta(hours=1),
            activity="job_triggered",
            detail={
                "trigger": {
                    "job_id": "5",
                    "job_type": "Export historical events V2",
                    "payload": {},
                }
            },
        )
        PluginStorage.objects.create(
            plugin_config_id=self.plugin_configs[4].pk,
            key="EXPORT_PARAMETERS",
            value=json.dumps({"id": "5"}),
        )

        # Case 6: Started export with storage containing another that's running
        self.create_entry(
            self.plugin_configs[5].pk,
            created_at=timezone.now() - timedelta(hours=1),
            activity="job_triggered",
            detail={
                "trigger": {
                    "job_id": "6",
                    "job_type": "Export historical events V2",
                    "payload": {},
                }
            },
        )
        PluginStorage.objects.create(
            plugin_config_id=self.plugin_configs[5].pk,
            key="EXPORT_PARAMETERS",
            value=json.dumps({"id": "7"}),
        )

        migration = importlib.import_module("posthog.migrations.0273_mark_inactive_exports_as_finished")
        executor = MigrationExecutor(connection)
        apps = executor.loader.project_state().apps

        # As we are not testing with the old model state, we need to manually
        # remove the activity entries to ensure that the migration code would
        # create them.
        ActivityLog.objects.filter(activity="export_fail", is_system=True).delete()
        migration.mark_inactive_exports_as_finished(apps, None)

        entries = ActivityLog.objects.filter(activity="export_fail", is_system=True)

        self.assertEqual({entry.detail["trigger"]["job_id"] for entry in entries}, {"1", "6"})
        self.assertEqual(
            {entry.detail["trigger"]["failure_reason"] for entry in entries},
            {"Export was killed after too much inactivity"},
        )

    def create_entry(self, plugin_config_id, activity, created_at, detail):
        ActivityLog.objects.create(
            team_id=self.team.pk,
            organization_id=self.organization.pk,
            scope="PluginConfig",
            item_id=plugin_config_id,
            activity=activity,
            detail=detail,
            created_at=created_at,
        )
