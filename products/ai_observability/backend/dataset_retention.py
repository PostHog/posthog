import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from products.ai_observability.backend.models.datasets import Dataset, DatasetItem, DatasetItemVersion, DatasetRevision
from products.ai_observability.backend.models.offline_evaluations import OfflineExperiment

ACTIVE_RETENTION = timedelta(days=90)
HISTORY_RETENTION = timedelta(days=30)
USAGE_REFRESH_INTERVAL = timedelta(hours=12)
EXPIRING_SOON_WINDOW = timedelta(days=7)
BATCH_SIZE = 500
MAX_DATASETS_PER_RUN = 100
TIME_BUDGET_SECONDS = 180


class DatasetRetentionPolicy:
    @staticmethod
    def dataset_expires_at(dataset: Dataset) -> datetime | None:
        if dataset.last_used_at is None:
            return None
        return (
            dataset.last_used_at
            + (HISTORY_RETENTION if dataset.archived else ACTIVE_RETENTION)
            + USAGE_REFRESH_INTERVAL
        )

    @staticmethod
    def revision_expires_at(revision: DatasetRevision) -> datetime | None:
        dataset = revision.dataset
        if dataset.current_revision_id == revision.id:
            return DatasetRetentionPolicy.dataset_expires_at(dataset)
        if revision.last_used_at is None:
            return None
        expires_at = revision.last_used_at + HISTORY_RETENTION + USAGE_REFRESH_INTERVAL
        dataset_expires_at = DatasetRetentionPolicy.dataset_expires_at(dataset)
        return min(expires_at, dataset_expires_at) if dataset_expires_at else expires_at

    @staticmethod
    def expiring_soon(expires_at: datetime | None) -> bool:
        return expires_at is not None and expires_at <= timezone.now() + EXPIRING_SOON_WINDOW


class DatasetUsage:
    @staticmethod
    def record(dataset: Dataset, revision: DatasetRevision | None = None) -> None:
        if dataset.expired_at is not None:
            raise Dataset.DoesNotExist
        if revision is not None and (revision.expired_at is not None or revision.dataset_id != dataset.id):
            raise DatasetRevision.DoesNotExist
        now = timezone.now()
        cutoff = now - USAGE_REFRESH_INTERVAL
        if dataset.last_used_at is not None and dataset.last_used_at > cutoff:
            if revision is None or (revision.last_used_at is not None and revision.last_used_at > cutoff):
                return
        # Usage and cleanup serialize on the dataset, including accesses to its older revisions.
        with transaction.atomic():
            locked = (
                Dataset.objects.for_team(dataset.team_id, canonical=True)
                .select_for_update()
                .get(id=dataset.id, expired_at__isnull=True)
            )
            if revision is not None:
                revisions = DatasetRevision.objects.for_team(dataset.team_id, canonical=True).filter(
                    id=revision.id, dataset_id=dataset.id, expired_at__isnull=True
                )
                if not revisions.exists():
                    raise DatasetRevision.DoesNotExist
                if revisions.filter(Q(last_used_at__isnull=True) | Q(last_used_at__lte=cutoff)).update(
                    last_used_at=now
                ):
                    revision.last_used_at = now
                else:
                    revision.last_used_at = revisions.values_list("last_used_at", flat=True).get()
            if locked.last_used_at is None or locked.last_used_at <= cutoff:
                Dataset.objects.for_team(dataset.team_id, canonical=True).filter(id=dataset.id).update(last_used_at=now)
                locked.last_used_at = now
            dataset.last_used_at = locked.last_used_at

    @staticmethod
    def record_versions(dataset: Dataset, versions: Sequence[DatasetItemVersion]) -> None:
        now = timezone.now()
        cutoff = now - USAGE_REFRESH_INTERVAL
        stale_ids = [v.id for v in versions if v.last_used_at is None or v.last_used_at <= cutoff]
        DatasetUsage.record(dataset)
        if not stale_ids:
            return
        with transaction.atomic():
            Dataset.objects.for_team(dataset.team_id, canonical=True).select_for_update().get(
                id=dataset.id, expired_at__isnull=True
            )
            queryset = DatasetItemVersion.objects.for_team(dataset.team_id, canonical=True).filter(
                dataset_id=dataset.id, id__in=stale_ids
            )
            if queryset.count() != len(stale_ids):
                raise DatasetItemVersion.DoesNotExist
            queryset.filter(Q(last_used_at__isnull=True) | Q(last_used_at__lte=cutoff)).update(last_used_at=now)

    @staticmethod
    def read_revision(dataset: Dataset, number: int | None = None) -> DatasetRevision | None:
        revisions = DatasetRevision.objects.for_team(dataset.team_id, canonical=True).filter(
            dataset_id=dataset.id, expired_at__isnull=True
        )
        revision: DatasetRevision | None
        if number is not None:
            revision = revisions.get(revision=number)
        elif dataset.current_revision_id is not None:
            revision = revisions.get(id=dataset.current_revision_id)
        else:
            revision = revisions.order_by("-revision").first()
        DatasetUsage.record(dataset, revision)
        return revision


class DatasetRetention:
    def __init__(self) -> None:
        self.datasets_expired = 0
        self.revisions_expired = 0
        self.versions_deleted = 0
        self.datasets_deleted = 0
        self.budget_exhausted = False

    @staticmethod
    def _uploading_revisions(team_id: int) -> QuerySet[OfflineExperiment]:
        return OfflineExperiment.objects.for_team(team_id).filter(status=OfflineExperiment.Status.UPLOADING)

    @staticmethod
    def _unused_versions(dataset: Dataset, cutoff: datetime) -> QuerySet[DatasetItemVersion]:
        versions = DatasetItemVersion.objects.for_team(dataset.team_id, canonical=True).filter(dataset_id=dataset.id)
        next_revision = (
            versions.filter(dataset_item_id=OuterRef("dataset_item_id"), version__gt=OuterRef("version"))
            .order_by("version")
            .values("dataset_revision__revision")[:1]
        )
        retained_revision = DatasetRevision.objects.for_team(dataset.team_id, canonical=True).filter(
            dataset_id=dataset.id,
            expired_at__isnull=True,
            revision__gte=OuterRef("dataset_revision__revision"),
            revision__lt=OuterRef("next_revision_number"),
        )
        # The next version bounds the snapshots that need this one, including archive markers.
        return (
            versions.filter(last_used_at__lte=cutoff)
            .exclude(id=F("dataset_item__current_version_id"))
            .annotate(next_revision_number=Coalesce(Subquery(next_revision), 2_147_483_647))
            .filter(~Exists(retained_revision))
        )

    def _delete_expired_dataset_batch(self, dataset: Dataset) -> None:
        versions = DatasetItemVersion.objects.for_team(dataset.team_id, canonical=True).filter(dataset_id=dataset.id)
        ids = list(versions.order_by("id").values_list("id", flat=True)[:BATCH_SIZE])
        if ids:
            DatasetItem.objects.for_team(dataset.team_id, canonical=True).filter(
                dataset_id=dataset.id, current_version_id__in=ids
            ).update(current_version=None)
            versions.filter(id__in=ids).only("id").delete()
            self.versions_deleted += len(ids)
            return
        revisions = DatasetRevision.objects.for_team(dataset.team_id, canonical=True).filter(dataset_id=dataset.id)
        revision_ids = list(revisions.order_by("id").values_list("id", flat=True)[:BATCH_SIZE])
        if revision_ids:
            Dataset.objects.for_team(dataset.team_id, canonical=True).filter(id=dataset.id).update(
                current_revision=None
            )
            revisions.filter(id__in=revision_ids).delete()
            return
        dataset.delete()
        self.datasets_deleted += 1

    def _clean_dataset(self, team_id: int, dataset_id: UUID) -> None:
        with transaction.atomic():
            dataset = (
                Dataset.objects.for_team(team_id, canonical=True)
                .select_for_update(skip_locked=True)
                .filter(id=dataset_id)
                .first()
            )
            if dataset is None:
                return
            now = timezone.now()
            Dataset.objects.for_team(team_id, canonical=True).filter(id=dataset.id).update(retention_checked_at=now)
            uploading = self._uploading_revisions(team_id).filter(dataset_revision__dataset_id=dataset.id)
            if dataset.expired_at is not None:
                self._delete_expired_dataset_batch(dataset)
                return
            if dataset.last_used_at is None:
                Dataset.objects.for_team(team_id, canonical=True).filter(id=dataset.id).update(last_used_at=now)
                return
            expires_at = DatasetRetentionPolicy.dataset_expires_at(dataset)
            if expires_at is not None and expires_at <= now and not uploading.exists():
                dataset.expired_at = now
                dataset.save(update_fields=["expired_at"])
                self._delete_expired_dataset_batch(dataset)
                self.datasets_expired += 1
                return
            cutoff = now - HISTORY_RETENTION - USAGE_REFRESH_INTERVAL
            revisions = DatasetRevision.objects.for_team(team_id, canonical=True).filter(dataset_id=dataset.id)
            current_revision_id = dataset.current_revision_id
            if current_revision_id is None:
                current_revision_id = revisions.order_by("-revision").values_list("id", flat=True).first()
            uninitialized_revisions = list(
                revisions.filter(last_used_at__isnull=True).values_list("id", flat=True)[:BATCH_SIZE]
            )
            revisions.filter(id__in=uninitialized_revisions).update(last_used_at=now)
            versions = DatasetItemVersion.objects.for_team(team_id, canonical=True).filter(dataset_id=dataset.id)
            uninitialized_versions = list(
                versions.filter(last_used_at__isnull=True).values_list("id", flat=True)[:BATCH_SIZE]
            )
            versions.filter(id__in=uninitialized_versions).update(last_used_at=now)
            eligible_revisions = revisions.filter(expired_at__isnull=True, last_used_at__lte=cutoff)
            if current_revision_id is not None:
                eligible_revisions = eligible_revisions.exclude(id=current_revision_id)
            revision_ids = list(
                eligible_revisions.exclude(id__in=uploading.values("dataset_revision_id"))
                .order_by("last_used_at", "id")
                .values_list("id", flat=True)[:BATCH_SIZE]
            )
            expired_count = revisions.filter(id__in=revision_ids).update(expired_at=now)
            ids = list(self._unused_versions(dataset, cutoff).order_by("id").values_list("id", flat=True)[:BATCH_SIZE])
            DatasetItemVersion.objects.for_team(team_id, canonical=True).filter(id__in=ids, dataset_id=dataset.id).only(
                "id"
            ).delete()
            # Keep revision identities while a surviving version or an evaluation still references them.
            removable_revisions = revisions.filter(expired_at__isnull=False).filter(
                ~Exists(
                    DatasetItemVersion.objects.for_team(team_id, canonical=True).filter(
                        dataset_revision_id=OuterRef("id")
                    )
                ),
                ~Exists(OfflineExperiment.objects.for_team(team_id).filter(dataset_revision_id=OuterRef("id"))),
            )
            empty_ids = list(removable_revisions.order_by("id").values_list("id", flat=True)[:BATCH_SIZE])
            revisions.filter(id__in=empty_ids).delete()
            self.revisions_expired += expired_count
            self.versions_deleted += len(ids)

    def run(self) -> None:
        deadline = time.monotonic() + TIME_BUDGET_SECONDS
        now = timezone.now()
        history_cutoff = now - HISTORY_RETENTION - USAGE_REFRESH_INTERVAL
        active_cutoff = now - ACTIVE_RETENTION - USAGE_REFRESH_INTERVAL
        old_revisions = (
            DatasetRevision.objects.unscoped()
            .filter(Q(last_used_at__isnull=True) | Q(last_used_at__lte=history_cutoff))
            .exclude(id=F("dataset__current_revision_id"))
        )
        candidates = (
            Dataset.objects.unscoped()
            .filter(
                Q(expired_at__isnull=False)
                | Q(last_used_at__isnull=True)
                | Q(archived=True, last_used_at__lte=history_cutoff)
                | Q(archived=False, last_used_at__lte=active_cutoff)
                | Q(id__in=old_revisions.values("dataset_id"))
            )
            .order_by(F("retention_checked_at").asc(nulls_first=True), "id")
            .values_list("id", "team_id")[:MAX_DATASETS_PER_RUN]
        )
        for dataset_id, team_id in candidates:
            if time.monotonic() >= deadline:
                self.budget_exhausted = True
                break
            datasets_expired = self.datasets_expired
            revisions_expired = self.revisions_expired
            versions_deleted = self.versions_deleted
            datasets_deleted = self.datasets_deleted
            try:
                self._clean_dataset(team_id, dataset_id)
            except Exception:
                self.datasets_expired = datasets_expired
                self.revisions_expired = revisions_expired
                self.versions_deleted = versions_deleted
                self.datasets_deleted = datasets_deleted
                raise
