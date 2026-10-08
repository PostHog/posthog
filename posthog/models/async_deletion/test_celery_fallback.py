from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.async_deletion.celery_fallback import celery_sweeps_enabled, dagster_sweep_is_active

GATE = "posthog.models.async_deletion.celery_fallback"


class TestCelerySweepGating(SimpleTestCase):
    @parameterized.expand(
        [
            ("cloud_us", "US", False, False),
            ("cloud_eu", "EU", False, False),
            ("cloud_staging", "DEV", False, False),
            ("e2e", "E2E", False, False),
            ("local_dev_explicit", "LOCAL", False, False),
            ("local_dev_via_debug", None, True, False),
            ("self_hosted", None, False, True),
        ]
    )
    def test_only_self_hosted_runs_the_celery_sweeps(self, _name, cloud_deployment, debug, expected):
        with (
            override_settings(CLOUD_DEPLOYMENT=cloud_deployment, DEBUG=debug),
            patch(f"{GATE}.dagster_sweep_is_active", return_value=False),
        ):
            assert celery_sweeps_enabled() is expected

    def test_a_misspelled_cloud_deployment_is_caught_only_by_the_dagster_check(self):
        # derive_run_mode maps an unrecognized value to HOBBY, so is_hobby() reads true here.
        with override_settings(CLOUD_DEPLOYMENT="us-east-1", DEBUG=False):
            with patch(f"{GATE}.dagster_sweep_is_active", return_value=True):
                assert celery_sweeps_enabled() is False
            with patch(f"{GATE}.dagster_sweep_is_active", return_value=False):
                assert celery_sweeps_enabled() is True

    @parameterized.expand([("ran", [[3]], True), ("never_ran", [[0]], False)])
    def test_the_dagster_check_reads_the_sweep_counter(self, _name, rows, expected):
        with patch(f"{GATE}.sync_execute", return_value=rows):
            assert dagster_sweep_is_active() is expected

    def test_unreadable_counters_mean_no_dagster_sweep(self):
        # A self-hosted install may not have the table, which must not block the sweep.
        with patch(f"{GATE}.sync_execute", side_effect=Exception("no such table")):
            assert dagster_sweep_is_active() is False


class TestCelerySweepTaskGuards(SimpleTestCase):
    @parameterized.expand(
        [
            ("cohorts", "posthog.tasks.tasks.clickhouse_clear_removed_data", "delete_cohorts.sweep_cohort_deletions"),
            (
                "persons",
                "posthog.tasks.tasks.clear_clickhouse_deleted_person",
                "delete_person.remove_deleted_person_data",
            ),
        ]
    )
    def test_the_task_does_nothing_when_gating_says_no(self, _name, task_path, swept_path):
        # The second layer: a beat schedule that survived a deploy must not sweep.
        from importlib import import_module

        module, _, name = task_path.rpartition(".")
        task = getattr(import_module(module), name)
        with (
            patch(f"{GATE}.celery_sweeps_enabled", return_value=False),
            patch(f"posthog.models.async_deletion.{swept_path}") as swept,
        ):
            task()
        swept.assert_not_called()
