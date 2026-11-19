from datetime import UTC, datetime

import pytest

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.admin.admins.async_deletion_admin import AsyncDeletionAdmin, deletion_status
from posthog.models.async_deletion import AsyncDeletion, DeletionRunJob, DeletionRunLog, DeletionRunStatus, DeletionType

WATERMARK = datetime(2026, 10, 15, 22, 0, tzinfo=UTC)
BEFORE = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
AFTER = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


class TestDeletionStatus(SimpleTestCase):
    @parameterized.expand(
        [
            ("verified", DeletionType.Person, AFTER, AFTER, WATERMARK, "Deleted on 2026-10-17 09:00 UTC"),
            (
                "person_after_watermark",
                DeletionType.Person,
                AFTER,
                None,
                WATERMARK,
                "Waiting for the person overrides squash. The last run reached 2026-10-15 22:00 UTC.",
            ),
            (
                "person_without_a_run",
                DeletionType.Person,
                BEFORE,
                None,
                None,
                "Waiting for the person overrides squash. No run recorded yet.",
            ),
            (
                "person_before_watermark",
                DeletionType.Person,
                BEFORE,
                None,
                WATERMARK,
                "Queued for the next deletes_job run",
            ),
            ("team_after_watermark", DeletionType.Team, AFTER, None, WATERMARK, "Queued for the next deletes_job run"),
            ("group", DeletionType.Group, AFTER, None, WATERMARK, "Pending. Not handled by deletes_job."),
        ]
    )
    def test_status(self, _name, deletion_type, created_at, verified_at, watermark, expected) -> None:
        deletion = AsyncDeletion(
            deletion_type=deletion_type, team_id=1, key="k", created_at=created_at, delete_verified_at=verified_at
        )
        assert deletion_status(deletion, watermark) == expected


@pytest.mark.django_db
def test_a_run_without_a_watermark_does_not_hide_the_last_known_watermark(team) -> None:
    deletion = AsyncDeletion.objects.create(deletion_type=DeletionType.Person, team_id=team.pk, key="k")
    AsyncDeletion.objects.filter(pk=deletion.pk).update(created_at=BEFORE)
    DeletionRunLog.record(
        "full",
        DeletionRunJob.DELETES,
        None,
        started_at=WATERMARK,
        watermark=WATERMARK,
        status=DeletionRunStatus.SUCCEEDED,
    )
    DeletionRunLog.record(
        "ends_only", DeletionRunJob.DELETES, None, started_at=AFTER, status=DeletionRunStatus.SUCCEEDED
    )

    admin = AsyncDeletionAdmin(AsyncDeletion, AdminSite())
    row = admin.get_queryset(RequestFactory().get("/")).get(pk=deletion.pk)

    assert admin.status(row) == "Queued for the next deletes_job run"
