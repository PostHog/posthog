from posthog.test.base import APIBaseTest

from rest_framework import status

from products.agent_memory.backend import logic


class TestAgentMemoryViewSet(APIBaseTest):
    def _base(self) -> str:
        return f"/api/projects/{self.team.id}/agent_memory"

    def test_write_then_read(self) -> None:
        response = self.client.post(
            f"{self._base()}/write/",
            {"path": "project.md", "content": "# Project memory"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert data["path"] == "project.md"
        assert data["version"] == 1
        assert data["updated_by_id"] == self.user.id

        read = self.client.get(f"{self._base()}/read/", {"path": "project.md"})
        assert read.status_code == status.HTTP_200_OK
        assert read.json()["content"] == "# Project memory"

    def test_read_missing_returns_404(self) -> None:
        response = self.client.get(f"{self._base()}/read/", {"path": "absent.md"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_write_invalid_path_returns_400(self) -> None:
        response = self.client.post(f"{self._base()}/write/", {"path": "../escape.md", "content": "x"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cas_conflict_returns_409_with_actual_version(self) -> None:
        self.client.post(f"{self._base()}/write/", {"path": "p.md", "content": "v1"}, format="json")
        # Update to v2.
        self.client.post(
            f"{self._base()}/write/", {"path": "p.md", "content": "v2", "expected_version": 1}, format="json"
        )
        # Stale write with expected_version=1 must conflict.
        response = self.client.post(
            f"{self._base()}/write/", {"path": "p.md", "content": "v3", "expected_version": 1}, format="json"
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        assert body["code"] == "version_conflict"
        assert body["expected_version"] == 1
        assert body["actual_version"] == 2

    def test_write_records_updated_by_run(self) -> None:
        response = self.client.post(
            f"{self._base()}/write/",
            {"path": "project.md", "content": "x", "updated_by_run": "run-123"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["updated_by_run"] == "run-123"

    def test_append_section(self) -> None:
        response = self.client.post(
            f"{self._base()}/append/",
            {"path": "project.md", "heading": "Conventions", "body": "Use snake_case."},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert "## Conventions" in response.json()["content"]
        assert "Use snake_case." in response.json()["content"]

    def test_list_with_prefix(self) -> None:
        for path in ["project.md", "users/jane.md", "users/john.md"]:
            self.client.post(f"{self._base()}/write/", {"path": path, "content": "x"}, format="json")

        response = self.client.get(f"{self._base()}/", {"prefix": "users/"})
        assert response.status_code == status.HTTP_200_OK
        paths = sorted(item["path"] for item in response.json())
        assert paths == ["users/jane.md", "users/john.md"]

    def test_delete_file(self) -> None:
        self.client.post(f"{self._base()}/write/", {"path": "p.md", "content": "x"}, format="json")
        response = self.client.delete(f"{self._base()}/file/?path=p.md")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["deleted"] is True
        # Second delete is idempotent.
        again = self.client.delete(f"{self._base()}/file/?path=p.md")
        assert again.json()["deleted"] is False

    def test_other_team_cannot_read(self) -> None:
        logic.write_memory(team_id=self.team.id, path="secret.md", content="ours", expected_version=None)
        other_team = self.organization.teams.create(name="Other")  # same org, different team
        response = self.client.get(f"/api/projects/{other_team.id}/agent_memory/read/", {"path": "secret.md"})
        # The file exists for self.team, not other_team — must be 404 for other_team.
        assert response.status_code == status.HTTP_404_NOT_FOUND
