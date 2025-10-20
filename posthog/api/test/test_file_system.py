from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.utils.timezone import now

from rest_framework import status

from posthog.models.file_system.file_system import FileSystem
from posthog.models.file_system.file_system_view_log import FileSystemViewLog


class TestFileSystemOrdering(APIBaseTest):
    def test_order_by_last_viewed_at_desc(self) -> None:
        timestamp = now()

        FileSystem.objects.create(
            team=self.team,
            path="Testing/First",
            depth=2,
            type="insight",
            ref="first",
            shortcut=False,
            created_by=self.user,
            created_at=timestamp - timedelta(days=3),
        )
        FileSystem.objects.create(
            team=self.team,
            path="Testing/Second",
            depth=2,
            type="insight",
            ref="second",
            shortcut=False,
            created_by=self.user,
            created_at=timestamp - timedelta(days=2),
        )
        FileSystem.objects.create(
            team=self.team,
            path="Testing/Third",
            depth=2,
            type="insight",
            ref="third",
            shortcut=False,
            created_by=self.user,
            created_at=timestamp - timedelta(days=1),
        )
        FileSystem.objects.create(
            team=self.team,
            path="Testing/Fourth",
            depth=2,
            type="insight",
            ref="fourth",
            shortcut=False,
            created_by=self.user,
            created_at=timestamp - timedelta(hours=12),
        )

        FileSystemViewLog.objects.create(
            team=self.team,
            user=self.user,
            type="insight",
            ref="first",
            viewed_at=timestamp - timedelta(hours=3),
        )
        FileSystemViewLog.objects.create(
            team=self.team,
            user=self.user,
            type="insight",
            ref="second",
            viewed_at=timestamp - timedelta(hours=1),
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/file_system/",
            {"order_by": "-last_viewed_at", "parent": "Testing", "not_type": "folder"},
        )

        assert response.status_code == status.HTTP_200_OK

        paths = [item["path"] for item in response.json()["results"]]
        assert paths == ["Testing/Second", "Testing/First", "Testing/Fourth", "Testing/Third"]
