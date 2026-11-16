from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import time_machine
from unittest.mock import patch

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.instance_setting import override_instance_config, set_instance_setting

from products.ai_observability.backend.dataset_queries import dataset_item_versions_at_revision
from products.ai_observability.backend.dataset_retention import (
    ACTIVE_RETENTION,
    HISTORY_RETENTION,
    RETENTION_ENABLED_SETTING,
    USAGE_REFRESH_INTERVAL,
    DatasetRetention,
    DatasetRetentionPolicy,
    DatasetUsage,
)
from products.ai_observability.backend.dataset_service import (
    DatasetItemMutationResult,
    DatasetMutationConflict,
    archive_dataset,
    archive_dataset_item,
    create_dataset,
    create_dataset_item,
    restore_dataset_item,
    update_dataset_item,
)
from products.ai_observability.backend.models.datasets import Dataset, DatasetItemVersion, DatasetRevision
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationUsageLedger,
    OfflineExperiment,
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


@time_machine.travel("2026-11-03T12:00:00Z", tick=False)
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
        self.update_item(first)
        self.age_history()
        second.version.dataset_revision.last_used_at = timezone.now()
        second.version.dataset_revision.save(update_fields=["last_used_at"])
        snapshot = dataset_item_versions_at_revision(
            team_id=self.team.id,
            dataset_id=self.dataset.id,
            revision=second.version.dataset_revision.revision,
            archived=False,
        )
        before = list(snapshot.values_list("id", flat=True))
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
        self.assertCountEqual(snapshot.values_list("id", flat=True), before)
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
        restore_dataset_item(
            team_id=self.team.id, dataset_id=self.dataset.id, item_id=first.item.id, created_by=None, base_version=2
        )
        self.dataset.refresh_from_db()
        self.age_history()
        first.version.dataset_revision.last_used_at = timezone.now()
        first.version.dataset_revision.save(update_fields=["last_used_at"])
        second.version.dataset_revision.last_used_at = timezone.now()
        second.version.dataset_revision.save(update_fields=["last_used_at"])
        before = list(
            dataset_item_versions_at_revision(
                team_id=self.team.id,
                dataset_id=self.dataset.id,
                revision=second.version.dataset_revision.revision,
                archived=False,
            ).values_list("id", flat=True)
        )
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
        self.assertEqual(list(snapshot.values_list("id", flat=True)), before)

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
        first.version.dataset_revision.last_used_at = timezone.now()
        first.version.dataset_revision.save(update_fields=["last_used_at"])
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

    def test_expired_shared_history_no_longer_uses_a_cleanup_slot(self) -> None:
        first = self.create_item()
        self.create_item("Second item")
        self.age_history()
        DatasetRetention().run()
        self.dataset.refresh_from_db()
        first.version.dataset_revision.refresh_from_db()
        self.assertIsNotNone(first.version.dataset_revision.expired_at)
        other = Dataset.objects.for_team(self.team.id, canonical=True).create(
            team=self.team, name="Needs cleanup", last_used_at=self.old, retention_checked_at=timezone.now()
        )
        checked_at = self.dataset.retention_checked_at
        with patch("products.ai_observability.backend.dataset_retention.MAX_DATASETS_PER_RUN", 1):
            DatasetRetention().run()
        self.assertFalse(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=other.id).exists())
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.retention_checked_at, checked_at)

    @parameterized.expand([("active", False), ("abandoned", True)])
    def test_upload_protection_uses_snapshot_activity(self, _name: str, abandoned: bool) -> None:
        first = self.create_item()
        experiment = (
            OfflineExperimentService(team_id=self.team.id, user_access_control=None)
            .create(
                ExperimentSubmission(
                    id=uuid4(),
                    name="Upload activity",
                    started_at=self.old,
                    dataset_revision_id=first.version.dataset_revision_id,
                )
            )
            .experiment
        )
        OfflineExperiment.objects.for_team(self.team.id).filter(id=experiment.id).update(created_at=self.old)
        self.dataset.last_used_at = self.old
        self.dataset.save(update_fields=["last_used_at"])
        if abandoned:
            self.age_history()
        DatasetRetention().run()
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.expired_at is not None, abandoned)
        experiment.refresh_from_db()
        self.assertEqual(experiment.status, OfflineExperiment.Status.UPLOADING)

    def test_result_only_upload_refreshes_snapshot_activity(self) -> None:
        first = self.create_item()
        experiment = (
            OfflineExperimentService(team_id=self.team.id, user_access_control=None)
            .create(
                ExperimentSubmission(
                    id=uuid4(),
                    name="Result batches",
                    started_at=self.old,
                    dataset_revision_id=first.version.dataset_revision_id,
                )
            )
            .experiment
        )
        ingestion = OfflineEvaluationIngestionService(team_id=self.team.id, user_access_control=None)
        item_id = uuid4()
        ingestion.upload(
            experiment.id,
            UploadSubmission(items=[ItemSubmission(id=item_id, dataset_item_version_id=first.version.id)], results=[]),
        )
        definition = ScoreDefinition.objects.create(team=self.team, name="Quality", kind="numeric")
        scorer = definition.create_new_version(config={}, created_by=None)
        self.age_history()
        self.dataset.last_used_at = self.old
        self.dataset.save(update_fields=["last_used_at"])
        ingestion.upload(
            experiment.id,
            UploadSubmission(
                items=[],
                results=[ResultSubmission(item_id=item_id, scorer_version_id=scorer.id, status="ok", value=1.0)],
            ),
        )
        DatasetRetention().run()
        first.version.dataset_revision.refresh_from_db()
        self.dataset.refresh_from_db()
        self.assertIsNone(self.dataset.expired_at)
        self.assertIsNone(first.version.dataset_revision.expired_at)
        assert first.version.dataset_revision.last_used_at is not None
        self.assertGreater(first.version.dataset_revision.last_used_at, self.old)

    def test_disabled_cleanup_preserves_pending_deletions_and_can_resume(self) -> None:
        self.create_item()
        self.dataset.expired_at = timezone.now()
        self.dataset.save(update_fields=["expired_at"])
        with override_instance_config(RETENTION_ENABLED_SETTING, False):
            sweep = DatasetRetention()
            sweep.run()
            self.assertTrue(sweep.disabled)
            self.assertTrue(DatasetItemVersion.objects.for_team(self.team.id).filter(dataset=self.dataset).exists())
            set_instance_setting(RETENTION_ENABLED_SETTING, True)
            DatasetRetention().run()
            self.assertFalse(DatasetItemVersion.objects.for_team(self.team.id).filter(dataset=self.dataset).exists())

    def test_disabling_during_a_sweep_stops_before_the_next_dataset(self) -> None:
        other = Dataset.objects.for_team(self.team.id, canonical=True).create(
            team=self.team, name="Next dataset", last_used_at=self.old, retention_checked_at=timezone.now()
        )
        self.dataset.last_used_at = self.old
        self.dataset.save(update_fields=["last_used_at"])
        clean_dataset = DatasetRetention._clean_dataset

        def disable_after_cleanup(sweep: DatasetRetention, team_id: int, dataset_id: UUID) -> None:
            clean_dataset(sweep, team_id, dataset_id)
            set_instance_setting(RETENTION_ENABLED_SETTING, False)

        with (
            override_instance_config(RETENTION_ENABLED_SETTING, True),
            patch.object(DatasetRetention, "_clean_dataset", disable_after_cleanup),
        ):
            sweep = DatasetRetention()
            sweep.run()
        self.assertTrue(sweep.disabled)
        self.assertFalse(Dataset.objects.for_team(self.team.id).filter(id=self.dataset.id).exists())
        self.assertTrue(Dataset.objects.for_team(self.team.id).filter(id=other.id).exists())

    @parameterized.expand([("dataset", True), ("history", False)])
    def test_evaluation_references_are_detached_in_batches(self, _name: str, expire_dataset: bool) -> None:
        first = self.create_item()
        lifecycle = OfflineExperimentService(team_id=self.team.id, user_access_control=None)
        ingestion = OfflineEvaluationIngestionService(team_id=self.team.id, user_access_control=None)
        experiment_ids = []
        for index in range(3):
            experiment = lifecycle.create(
                ExperimentSubmission(
                    id=uuid4(),
                    name=f"Repeated evaluation {index}",
                    started_at=timezone.now(),
                    dataset_revision_id=first.version.dataset_revision_id,
                )
            ).experiment
            experiment_ids.append(experiment.id)
            ingestion.upload(
                experiment.id,
                UploadSubmission(
                    items=[ItemSubmission(id=uuid4(), dataset_item_version_id=first.version.id)], results=[]
                ),
            )
            lifecycle.close(experiment.id, status="completed")
        if not expire_dataset:
            self.update_item(first)
        self.age_history()
        if expire_dataset:
            self.dataset.last_used_at = self.old
            self.dataset.save(update_fields=["last_used_at"])

        items = OfflineExperimentItem.objects.for_team(self.team.id).filter(experiment_id__in=experiment_ids)
        experiments = OfflineExperiment.objects.for_team(self.team.id).filter(id__in=experiment_ids)
        versions = DatasetItemVersion.objects.for_team(self.team.id, canonical=True).filter(id=first.version.id)
        with patch("products.ai_observability.backend.dataset_retention.BATCH_SIZE", 2):
            DatasetRetention().run()
            self.assertEqual(items.filter(dataset_item_version_id=first.version.id).count(), 1)
            self.assertTrue(versions.exists())
            self.assertEqual(experiments.filter(dataset_revision_id=first.version.dataset_revision_id).count(), 3)
            with patch("django.db.models.query.QuerySet.delete", side_effect=DatabaseError("Injected failure")):
                failed_sweep = DatasetRetention()
                failed_sweep.run()
            self.assertEqual(failed_sweep.datasets_failed, 1)
            self.assertEqual(items.filter(dataset_item_version_id=first.version.id).count(), 1)
            self.assertTrue(versions.exists())
            DatasetRetention().run()
            self.assertFalse(versions.exists())
            self.assertEqual(items.filter(dataset_item_version_id__isnull=True).count(), 3)
            DatasetRetention().run()
            self.assertEqual(
                experiments.filter(dataset_revision_id=first.version.dataset_revision_id).count(),
                1 if expire_dataset else 3,
            )
            self.assertTrue(
                DatasetRevision.objects.for_team(self.team.id, canonical=True)
                .filter(id=first.version.dataset_revision_id)
                .exists()
            )
            DatasetRetention().run()
            self.assertEqual(experiments.filter(dataset_revision_id__isnull=True).count(), 3 if expire_dataset else 0)
        self.assertEqual(items.filter(dataset_item_version_identifier=str(first.version.id)).count(), 3)
        self.assertEqual(
            experiments.filter(dataset_revision_identifier=str(first.version.dataset_revision_id)).count(), 3
        )

    def test_dataset_payload_deletion_is_batched_and_hidden_until_finished(self) -> None:
        first = self.create_item()
        second = self.create_item("Second item")
        self.dataset.last_used_at = self.old
        self.dataset.save()
        with patch("products.ai_observability.backend.dataset_retention.BATCH_SIZE", 1):
            sweep = DatasetRetention()
            with patch("products.ai_observability.backend.dataset_retention.logger.info") as log:
                with self.captureOnCommitCallbacks(execute=True):
                    sweep.run()
                    log.assert_not_called()
                log.assert_called_once_with(
                    "dataset_retention_dataset_cleaned",
                    team_id=self.team.id,
                    dataset_id=str(self.dataset.id),
                    datasets_expired=1,
                    revisions_expired=0,
                    versions_deleted=1,
                    datasets_deleted=0,
                )
            self.assertEqual(sweep.versions_deleted, 1)
            self.dataset.refresh_from_db()
            self.assertIsNotNone(self.dataset.expired_at)
            replacement = create_dataset(team=self.team, created_by=None, name=self.dataset.name)
            self.assertNotEqual(replacement.id, self.dataset.id)
            with self.assertRaises(DatasetMutationConflict):
                create_dataset(team=self.team, created_by=None, name=self.dataset.name)
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

    @parameterized.expand([(1, RuntimeError), (100, DatabaseError), (100, SoftTimeLimitExceeded)])
    def test_deletion_failure_rolls_back_content_without_starving_cleanup(
        self, max_datasets: int, error_type: type[Exception]
    ) -> None:
        first = self.create_item()
        self.dataset.last_used_at = self.old
        self.dataset.save()
        other = Dataset.objects.for_team(self.team.id, canonical=True).create(
            team=self.team, name="Another eligible dataset", last_used_at=self.old, retention_checked_at=self.old
        )
        sweep = DatasetRetention()
        with (
            patch("products.ai_observability.backend.dataset_retention.MAX_DATASETS_PER_RUN", max_datasets),
            patch("django.db.models.query.QuerySet.delete", side_effect=error_type("Injected failure")),
            patch("products.ai_observability.backend.dataset_retention.logger.info") as log,
            self.captureOnCommitCallbacks(execute=True),
        ):
            if error_type is SoftTimeLimitExceeded:
                with self.assertRaises(SoftTimeLimitExceeded):
                    sweep.run()
            else:
                sweep.run()
        self.assertFalse(any(call.kwargs.get("dataset_id") == str(self.dataset.id) for call in log.call_args_list))
        self.assertEqual(sweep.datasets_failed, 1)
        self.assertEqual(sweep.versions_deleted, 0)
        self.dataset.refresh_from_db()
        first.item.refresh_from_db()
        self.assertIsNone(self.dataset.expired_at)
        self.assertEqual(first.item.current_version_id, first.version.id)
        self.assertIsNotNone(self.dataset.retention_checked_at)
        if error_type is DatabaseError:
            self.assertFalse(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=other.id).exists())
        else:
            with patch("products.ai_observability.backend.dataset_retention.MAX_DATASETS_PER_RUN", 1):
                DatasetRetention().run()
            self.assertFalse(Dataset.objects.for_team(self.team.id, canonical=True).filter(id=other.id).exists())

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


@time_machine.travel("2026-11-03T12:00:00Z", tick=False)
class TestDatasetRetentionMigration(TransactionTestCase):
    def test_existing_content_receives_a_full_retention_period(self) -> None:
        _, _, team = Organization.objects.bootstrap(None)
        executor = MigrationExecutor(connection)
        before = [("ai_observability", "0070_offline_payload_expiry_indexes")]
        after = [("ai_observability", "0074_release_expired_dataset_names")]
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
            with self.assertRaises(IntegrityError), transaction.atomic():
                Dataset.objects.for_team(team.id, canonical=True).create(team_id=team.id, name=dataset.name)
            dataset.expired_at = timezone.now()
            dataset.save(update_fields=["expired_at"])
            replacement = Dataset.objects.for_team(team.id, canonical=True).create(team_id=team.id, name=dataset.name)
            self.assertNotEqual(dataset.id, replacement.id)
        finally:
            MigrationExecutor(connection).migrate(after)
