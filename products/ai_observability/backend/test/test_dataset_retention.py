from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

from unittest.mock import patch

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, Team

from products.ai_observability.backend.dataset_queries import dataset_item_versions_at_revision
from products.ai_observability.backend.dataset_retention import (
    ACTIVE_RETENTION,
    HISTORY_RETENTION,
    USAGE_REFRESH_INTERVAL,
    DatasetRetention,
    DatasetRetentionPolicy,
    DatasetUsage,
)
from products.ai_observability.backend.dataset_service import (
    DatasetItemMutationResult,
    archive_dataset,
    archive_dataset_item,
    create_dataset_item,
    update_dataset_item,
)
from products.ai_observability.backend.models.datasets import Dataset, DatasetItemVersion, DatasetRevision
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationUsageLedger,
    OfflineExperimentItem,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition
from products.ai_observability.backend.offline_evaluation_service import (
    OfflineEvaluationIngestionService,
    OfflineExperimentService,
)
from products.ai_observability.backend.offline_evaluation_types import (
    ExperimentSubmission,
    ItemSubmission,
    ResultSubmission,
    UploadSubmission,
)


class TestDatasetRetention(TestCase):
    team: Team

    @classmethod
    def setUpTestData(cls) -> None:
        _, _, cls.team = Organization.objects.bootstrap(None)

    def setUp(self) -> None:
        self.dataset = Dataset.objects.for_team(self.team.id, canonical=True).create(
            team=self.team, name="Retention fixture"
        )
        self.old = timezone.now() - ACTIVE_RETENTION - USAGE_REFRESH_INTERVAL - timedelta(days=1)

    def create_item(self, value: str = "First input") -> DatasetItemMutationResult:
        result = create_dataset_item(team_id=self.team.id, dataset_id=self.dataset.id, created_by=None, input=value)
        self.dataset.refresh_from_db()
        return result

    def update_item(self, result: DatasetItemMutationResult, value: str = "Updated input") -> DatasetItemMutationResult:
        updated = update_dataset_item(
            team_id=self.team.id,
            dataset_id=self.dataset.id,
            item_id=result.item.id,
            created_by=None,
            base_version=result.version.version,
            input=value,
        )
        self.dataset.refresh_from_db()
        return updated

    def age_history(self) -> None:
        DatasetRevision.objects.for_team(self.team.id, canonical=True).filter(dataset=self.dataset).update(
            last_used_at=self.old
        )
        DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(dataset=self.dataset).update(
            last_used_at=self.old
        )

    @parameterized.expand([(False, ACTIVE_RETENTION), (True, HISTORY_RETENTION)])
    def test_expiry_includes_the_usage_recording_margin(self, archived: bool, retention: timedelta) -> None:
        now = timezone.now()
        self.dataset.archived = archived
        self.dataset.last_used_at = now - retention
        self.dataset.save()
        DatasetRetention().run()
        self.assertTrue(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=self.dataset.id).exists())
        self.assertEqual(DatasetRetentionPolicy.dataset_expires_at(self.dataset), now + USAGE_REFRESH_INTERVAL)

        self.dataset.last_used_at -= USAGE_REFRESH_INTERVAL + timedelta(seconds=1)
        self.dataset.save()
        DatasetRetention().run()
        self.assertFalse(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=self.dataset.id).exists())

    def test_repeated_usage_needs_no_database_queries(self) -> None:
        item = self.create_item()
        with self.assertNumQueries(0):
            DatasetUsage.record(self.dataset, item.version.dataset_revision)
        self.age_history()
        self.dataset.last_used_at = self.old
        self.dataset.save()
        item.version.dataset_revision.refresh_from_db()
        DatasetUsage.record(self.dataset, item.version.dataset_revision)
        with self.assertNumQueries(0):
            DatasetUsage.record(self.dataset, item.version.dataset_revision)
        assert self.dataset.last_used_at is not None
        assert item.version.dataset_revision.last_used_at is not None
        self.assertGreater(self.dataset.last_used_at, self.old)
        self.assertGreater(item.version.dataset_revision.last_used_at, self.old)

    def test_shared_version_survives_expired_introducing_revision(self) -> None:
        first = self.create_item()
        second = self.create_item("Second item")
        self.age_history()
        DatasetRetention().run()

        first.version.dataset_revision.refresh_from_db()
        self.assertIsNotNone(first.version.dataset_revision.expired_at)
        self.assertTrue(
            DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(id=first.version.id).exists()
        )
        snapshot = dataset_item_versions_at_revision(
            team_id=self.team.id,
            dataset_id=self.dataset.id,
            revision=second.version.dataset_revision.revision,
            archived=False,
        )
        self.assertCountEqual(snapshot.values_list("id", flat=True), [first.version.id, second.version.id])
        with self.assertRaises(DatasetRevision.DoesNotExist):
            DatasetUsage.read_revision(self.dataset, first.version.dataset_revision.revision)

    def test_obsolete_versions_are_deleted_and_numbers_are_not_reused(self) -> None:
        first = self.create_item()
        second = self.update_item(first)
        self.age_history()
        sweep = DatasetRetention()
        sweep.run()
        self.assertEqual(sweep.versions_deleted, 1)
        self.assertFalse(
            DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(id=first.version.id).exists()
        )
        third = self.update_item(second, "Third input")
        self.assertEqual(third.version.version, 3)
        self.assertEqual(third.version.dataset_revision.revision, 3)

    def test_archive_marker_prevents_resurrection_in_retained_snapshot(self) -> None:
        first = self.create_item()
        archived = archive_dataset_item(
            team_id=self.team.id, dataset_id=self.dataset.id, item_id=first.item.id, created_by=None, base_version=1
        )
        second = self.create_item("Second item")
        self.age_history()
        first.version.dataset_revision.last_used_at = timezone.now()
        first.version.dataset_revision.save(update_fields=["last_used_at"])
        DatasetRetention().run()
        self.assertTrue(
            DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(id=archived.version.id).exists()
        )
        snapshot = dataset_item_versions_at_revision(
            team_id=self.team.id,
            dataset_id=self.dataset.id,
            revision=second.version.dataset_revision.revision,
            archived=False,
        )
        self.assertEqual(list(snapshot.values_list("id", flat=True)), [second.version.id])

    def test_using_history_protects_only_the_requested_revision(self) -> None:
        first = self.create_item()
        second = self.update_item(first)
        self.update_item(second, "Third input")
        self.age_history()
        DatasetUsage.read_revision(self.dataset, first.version.dataset_revision.revision)
        DatasetRetention().run()
        self.assertTrue(
            DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(id=first.version.id).exists()
        )
        self.assertFalse(
            DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(id=second.version.id).exists()
        )

    def test_reading_item_history_preserves_its_payload(self) -> None:
        first = self.create_item()
        self.update_item(first)
        self.age_history()
        first.version.refresh_from_db()
        DatasetUsage.record_versions(self.dataset, [first.version])
        DatasetRetention().run()
        self.assertTrue(
            DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(id=first.version.id).exists()
        )

    def test_archiving_and_superseding_start_a_full_history_period(self) -> None:
        first = self.create_item()
        self.age_history()
        self.update_item(first)
        first.version.dataset_revision.refresh_from_db()
        assert first.version.dataset_revision.last_used_at is not None
        self.assertGreater(first.version.dataset_revision.last_used_at, timezone.now() - timedelta(seconds=5))
        self.dataset.last_used_at = self.old
        self.dataset.save()
        archive_dataset(team_id=self.team.id, dataset_id=self.dataset.id)
        self.dataset.refresh_from_db()
        expires_at = DatasetRetentionPolicy.dataset_expires_at(self.dataset)
        assert expires_at is not None
        self.assertGreater(expires_at, timezone.now() + HISTORY_RETENTION)

    def test_missing_usage_gets_a_full_grace_period(self) -> None:
        self.dataset.last_used_at = None
        self.dataset.save()
        DatasetRetention().run()
        self.dataset.refresh_from_db()
        self.assertIsNotNone(self.dataset.last_used_at)
        self.assertIsNone(self.dataset.expired_at)

    def test_uploading_evaluation_pins_snapshot_then_completed_history_survives_cleanup(self) -> None:
        first = self.create_item()
        lifecycle = OfflineExperimentService(team_id=self.team.id, user_access_control=None)
        experiment = lifecycle.create(
            ExperimentSubmission(
                id=uuid4(),
                name="Retention run",
                started_at=timezone.now(),
                dataset_revision_id=first.version.dataset_revision_id,
            )
        ).experiment
        definition = ScoreDefinition.objects.create(team=self.team, name="Quality", kind="numeric")
        scorer = definition.create_new_version(config={}, created_by=None)
        item_id = uuid4()
        OfflineEvaluationIngestionService(team_id=self.team.id, user_access_control=None).upload(
            experiment.id,
            UploadSubmission(
                items=[ItemSubmission(id=item_id, dataset_item_version_id=first.version.id)],
                results=[ResultSubmission(item_id=item_id, scorer_version_id=scorer.id, status="ok", value=1.0)],
            ),
        )
        self.update_item(first)
        self.age_history()
        self.dataset.last_used_at = self.old
        self.dataset.save()
        DatasetRetention().run()
        self.dataset.refresh_from_db()
        self.assertIsNone(self.dataset.expired_at)
        self.assertTrue(
            DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(id=first.version.id).exists()
        )
        lifecycle.close(experiment.id, status="completed")
        self.dataset.refresh_from_db()
        self.assertGreater(self.dataset.last_used_at, self.old)
        self.dataset.last_used_at = self.old
        self.dataset.save()
        for _ in range(3):
            DatasetRetention().run()
        self.assertFalse(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=self.dataset.id).exists())
        experiment.refresh_from_db()
        item = OfflineExperimentItem.objects.for_team(self.team.id).get(id=item_id)
        self.assertIsNone(experiment.dataset_revision_id)
        self.assertEqual(experiment.dataset_revision_identifier, str(first.version.dataset_revision_id))
        self.assertIsNone(item.dataset_item_version_id)
        self.assertEqual(item.dataset_item_version_identifier, str(first.version.id))
        self.assertTrue(OfflineEvaluationResult.objects.for_team(self.team.id).filter(item=item).exists())
        self.assertTrue(
            OfflineEvaluationUsageLedger.objects.for_team(self.team.id).filter(experiment_id=experiment.id).exists()
        )
        scorer.refresh_from_db()

    def test_cleanup_is_bounded_and_cannot_be_starved_by_pinned_history(self) -> None:
        first = self.create_item()
        self.update_item(first)
        OfflineExperimentService(team_id=self.team.id, user_access_control=None).create(
            ExperimentSubmission(
                id=uuid4(),
                name="Pinned snapshot",
                started_at=timezone.now(),
                dataset_revision_id=first.version.dataset_revision_id,
            )
        )
        self.age_history()
        self.dataset.retention_checked_at = None
        self.dataset.save()
        other = Dataset.objects.for_team(self.team.id, canonical=True).create(
            team=self.team, name="Other", last_used_at=self.old, retention_checked_at=timezone.now() - timedelta(days=1)
        )
        with patch("products.ai_observability.backend.dataset_retention.MAX_DATASETS_PER_RUN", 1):
            DatasetRetention().run()
            self.assertTrue(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=other.id).exists())
            DatasetRetention().run()
        self.assertFalse(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=other.id).exists())

    def test_dataset_payload_deletion_is_batched_and_hidden_until_finished(self) -> None:
        first = self.create_item()
        second = self.create_item("Second item")
        self.dataset.last_used_at = self.old
        self.dataset.save()
        with patch("products.ai_observability.backend.dataset_retention.BATCH_SIZE", 1):
            sweep = DatasetRetention()
            sweep.run()
            self.assertEqual(sweep.versions_deleted, 1)
            self.dataset.refresh_from_db()
            self.assertIsNotNone(self.dataset.expired_at)
            self.assertEqual(
                DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(dataset=self.dataset).count(),
                1,
            )
            for _ in range(4):
                DatasetRetention().run()
        self.assertFalse(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=self.dataset.id).exists())
        self.assertFalse(
            DatasetItemVersion.objects.for_team(self.team.id, canonical=True)
            .filter(id__in=[first.version.id, second.version.id])
            .exists()
        )

    def test_deletion_failure_rolls_back_expiry_and_current_version_pointer(self) -> None:
        first = self.create_item()
        self.dataset.last_used_at = self.old
        self.dataset.save()
        with patch("django.db.models.query.QuerySet.delete", side_effect=RuntimeError("Injected failure")):
            with self.assertRaises(RuntimeError), transaction.atomic():
                DatasetRetention().run()
        self.dataset.refresh_from_db()
        first.item.refresh_from_db()
        self.assertIsNone(self.dataset.expired_at)
        self.assertEqual(first.item.current_version_id, first.version.id)

    @parameterized.expand([(8, False), (7, True), (1, True)])
    def test_expiring_soon_window(self, days: int, expected: bool) -> None:
        self.assertEqual(DatasetRetentionPolicy.expiring_soon(timezone.now() + timedelta(days=days)), expected)


class TestDatasetRetentionConcurrency(TransactionTestCase):
    def setUp(self) -> None:
        _, _, self.team = Organization.objects.bootstrap(None)
        self.dataset = Dataset.objects.for_team(self.team.id, canonical=True).create(
            team=self.team, name="Concurrent retention", last_used_at=timezone.now() - timedelta(days=100)
        )

    @staticmethod
    def run_cleanup() -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '2s'")
            DatasetRetention().run()
        finally:
            connection.close()

    def test_cleanup_skips_a_usage_transaction_then_rechecks_the_new_timestamp(self) -> None:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                DatasetUsage.record(self.dataset)
                executor.submit(self.run_cleanup).result(timeout=10)
            executor.submit(self.run_cleanup).result(timeout=10)
        self.dataset.refresh_from_db()
        self.assertIsNone(self.dataset.expired_at)

    def test_usage_after_cleanup_cannot_resurrect_an_expired_dataset(self) -> None:
        create_dataset_item(team_id=self.team.id, dataset_id=self.dataset.id, created_by=None, input="Example")
        Dataset.objects.for_team(self.team.id, canonical=True).filter(id=self.dataset.id).update(
            last_used_at=self.dataset.last_used_at
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.run_cleanup).result(timeout=10)
        with self.assertRaises(Dataset.DoesNotExist):
            DatasetUsage.record(self.dataset)
        self.dataset.refresh_from_db()
        self.assertIsNotNone(self.dataset.expired_at)


class TestDatasetRetentionMigration(TransactionTestCase):
    def test_existing_content_receives_a_full_retention_period(self) -> None:
        _, _, team = Organization.objects.bootstrap(None)
        executor = MigrationExecutor(connection)
        before = [("ai_observability", "0070_offline_payload_expiry_indexes")]
        after = [("ai_observability", "0072_dataset_retention_indexes")]
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            legacy_dataset = apps.get_model("ai_observability", "Dataset").objects.create(
                team_id=team.id, name="Existing dataset"
            )
            legacy_revision = apps.get_model("ai_observability", "DatasetRevision").objects.create(
                team_id=team.id, dataset_id=legacy_dataset.id, revision=1
            )
            legacy_item = apps.get_model("ai_observability", "DatasetItem").objects.create(
                team_id=team.id, dataset_id=legacy_dataset.id
            )
            legacy_version = apps.get_model("ai_observability", "DatasetItemVersion").objects.create(
                team_id=team.id,
                dataset_id=legacy_dataset.id,
                dataset_item_id=legacy_item.id,
                dataset_revision_id=legacy_revision.id,
                version=1,
                input="Existing input",
            )
            started = timezone.now()
            MigrationExecutor(connection).migrate(after)
            dataset = Dataset.objects.for_team(team.id, canonical=True).get(id=legacy_dataset.id)
            revision = DatasetRevision.objects.for_team(team.id, canonical=True).get(id=legacy_revision.id)
            version = DatasetItemVersion.objects.for_team(team.id, canonical=True).get(id=legacy_version.id)
            assert dataset.last_used_at is not None
            assert revision.last_used_at is not None
            assert version.last_used_at is not None
            self.assertGreaterEqual(dataset.last_used_at, started)
            self.assertGreaterEqual(revision.last_used_at, started)
            self.assertGreaterEqual(version.last_used_at, started)
            DatasetRetention().run()
            self.assertTrue(DatasetItemVersion.objects.for_team(team.id, canonical=True).filter(id=version.id).exists())
        finally:
            MigrationExecutor(connection).migrate(after)
