import json
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone
from freezegun.api import freeze_time

from posthog.test.base import NonAtomicTestMigrations


@freeze_time("2021-08-25T13:00:00Z")
class MarkInactiveExportsAsFinished(NonAtomicTestMigrations):
    migrate_from = "0272_alter_organization_plugins_access_level"
    migrate_to = "0273_mark_inactive_exports_as_finished"

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        Team = apps.get_model("posthog", "Team")
        Plugin = apps.get_model("posthog", "Plugin")
        PluginConfig = apps.get_model("posthog", "PluginConfig")
        PluginStorage = apps.get_model("posthog", "PluginStorage")

        self.organization = Organization.objects.create()
        self.team = Team.objects.create(organization=self.organization, app_urls=[])
        self.plugins = [Plugin.objects.create(organization_id=self.organization.pk) for _ in range(6)]
        self.plugin_configs = [
            PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=i)
            for i, plugin in enumerate(self.plugins)
        ]

        # Case 1: Old non-finished export
        self.create_entry(
            apps,
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
            apps,
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
            apps,
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
            apps,
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
            apps,
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
            apps,
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
            apps,
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
            plugin_config_id=self.plugin_configs[4].pk, key="EXPORT_PARAMETERS", value=json.dumps({"id": "5"})
        )

        # Case 6: Started export with storage containing another that's running
        self.create_entry(
            apps,
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
            plugin_config_id=self.plugin_configs[5].pk, key="EXPORT_PARAMETERS", value=json.dumps({"id": "7"})
        )

    def _test_migration(self):
        ActivityLog = self.apps.get_model("posthog", "ActivityLog")  # type: ignore

        entries = ActivityLog.objects.filter(activity="export_fail", is_system=True)

        self.assertEqual(set(entry.detail["trigger"]["job_id"] for entry in entries), {"1", "6"})
        self.assertEqual(
            set(entry.detail["trigger"]["failure_reason"] for entry in entries),
            {"Export was killed after too much inactivity"},
        )

    def test_migration(self):
        try:
            self._test_migration()
        finally:
            # As we are using NonAtomicTestMigrations, we can't rely on the usual
            # transaction rollback that Djangos test runner would usually do.
            # Instead, the runner will call `django-admin.py flush` to clean up,
            # which requires that we are up to date on applied migrations.
            call_command("migrate", "posthog", verbosity=0)

    def create_entry(self, apps, plugin_config_id, activity, created_at, detail):
        ActivityLog = apps.get_model("posthog", "ActivityLog")
        ActivityLog.objects.create(
            team_id=self.team.pk,
            organization_id=self.organization.pk,
            scope="PluginConfig",
            item_id=plugin_config_id,
            activity=activity,
            detail=detail,
            created_at=created_at,
        )
