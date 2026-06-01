"""End-to-end viewset tests for the Tools & Skills registry."""

from __future__ import annotations

from typing import Any

from posthog.test.base import APIBaseTest

from rest_framework import status

from .models import AgentSkillTemplate


class TestSkillTemplateViewSet(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base_url = f"/api/projects/{self.team.id}/agent_skill_templates/"

    # ---- Create + retrieve + list ----

    def test_create_publishes_v1(self) -> None:
        res = self.client.post(
            self.base_url,
            data={
                "name": "research",
                "description": "How to research stuff",
                "body": "# Research\n\nDo the thing.",
            },
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_201_CREATED, res.content
        body = res.json()
        assert body["name"] == "research"
        assert body["version"] == 1
        assert body["is_latest"] is True
        assert body["body"] == "# Research\n\nDo the thing."

    def test_create_with_files(self) -> None:
        res = self.client.post(
            self.base_url,
            data={
                "name": "with-files",
                "body": "# Skill",
                "files": [
                    {"path": "examples/one.md", "content": "ex 1"},
                    {"path": "examples/two.md", "content": "ex 2"},
                ],
            },
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_201_CREATED, res.content
        body = res.json()
        assert len(body["files"]) == 2
        paths = sorted(f["path"] for f in body["files"])
        assert paths == ["examples/one.md", "examples/two.md"]

    def test_list_shows_only_latest(self) -> None:
        self._create("a")
        self._create("b")
        res = self.client.get(self.base_url)
        assert res.status_code == status.HTTP_200_OK
        names = [s["name"] for s in res.json()]
        assert set(names) == {"a", "b"}

    def test_retrieve_by_name_default_returns_latest(self) -> None:
        self._create("dup", body="v1")
        self._publish("dup", body="v2")
        res = self.client.get(f"{self.base_url}name/dup/")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["version"] == 2
        assert res.json()["body"] == "v2"

    def test_retrieve_by_name_with_version_param(self) -> None:
        self._create("histo", body="v1 body")
        self._publish("histo", body="v2 body")
        res = self.client.get(f"{self.base_url}name/histo/?version=1")
        assert res.json()["version"] == 1
        assert res.json()["body"] == "v1 body"

    def test_retrieve_missing_404s(self) -> None:
        res = self.client.get(f"{self.base_url}name/missing/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    # ---- Publish (overwrites + structured edits) ----

    def test_publish_with_full_body_overwrite(self) -> None:
        self._create("pub", body="v1")
        res = self._publish("pub", body="new v2")
        body = res.json()
        assert body["version"] == 2
        assert body["body"] == "new v2"

    def test_publish_with_structured_edits(self) -> None:
        self._create("edited", body="Hello world")
        res = self.client.post(
            f"{self.base_url}name/edited/publish/",
            data={"edits": [{"old": "world", "new": "Ben"}]},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_200_OK, res.content
        body = res.json()
        assert body["version"] == 2
        assert body["body"] == "Hello Ben"

    def test_publish_rejects_both_body_and_edits(self) -> None:
        self._create("conflict", body="hi")
        res = self.client.post(
            f"{self.base_url}name/conflict/publish/",
            data={"body": "x", "edits": [{"old": "hi", "new": "ok"}]},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_publish_returns_edit_index_on_no_match(self) -> None:
        self._create("missy", body="hello")
        res = self.client.post(
            f"{self.base_url}name/missy/publish/",
            data={"edits": [{"old": "GOODBYE", "new": "x"}]},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST, res.content
        body = res.json()
        assert body["extra"]["edit_index"] == 0
        assert "not found" in body["detail"]

    def test_publish_carries_files_forward(self) -> None:
        self._create(
            "carry",
            body="v1",
            files=[{"path": "a.md", "content": "alpha"}, {"path": "b.md", "content": "beta"}],
        )
        self._publish("carry", body="v2")
        res = self.client.get(f"{self.base_url}name/carry/")
        body = res.json()
        assert body["version"] == 2
        paths = sorted(f["path"] for f in body["files"])
        assert paths == ["a.md", "b.md"]

    # ---- Versions + history ----

    def test_versions_returns_newest_first(self) -> None:
        self._create("vh", body="v1")
        self._publish("vh", body="v2")
        self._publish("vh", body="v3")
        res = self.client.get(f"{self.base_url}name/vh/versions/")
        versions = [v["version"] for v in res.json()]
        assert versions == [3, 2, 1]
        assert res.json()[0]["is_latest"] is True
        assert res.json()[1]["is_latest"] is False

    # ---- Archive + duplicate ----

    def test_archive_soft_deletes_all_versions(self) -> None:
        self._create("ar", body="v1")
        self._publish("ar", body="v2")
        res = self.client.post(f"{self.base_url}name/ar/archive/")
        assert res.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(f"{self.base_url}name/ar/").status_code == status.HTTP_404_NOT_FOUND
        assert all(t.deleted for t in AgentSkillTemplate.objects.filter(name="ar"))

    def test_duplicate_under_new_name(self) -> None:
        self._create("orig", body="hello", files=[{"path": "a.md", "content": "a"}])
        res = self.client.post(
            f"{self.base_url}name/orig/duplicate/",
            data={"name": "copy"},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_201_CREATED, res.content
        body = res.json()
        assert body["name"] == "copy"
        assert body["version"] == 1
        assert body["body"] == "hello"
        assert len(body["files"]) == 1

    # ---- File CRUD ----

    def test_create_file_then_delete(self) -> None:
        self._create("fc", body="hi")
        res = self.client.post(
            f"{self.base_url}name/fc/files/",
            data={"path": "single.md", "content": "ex"},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_201_CREATED, res.content
        # Delete it.
        res = self.client.delete(f"{self.base_url}name/fc/files/single.md/")
        assert res.status_code == status.HTTP_204_NO_CONTENT
        # Not found after delete.
        res = self.client.delete(f"{self.base_url}name/fc/files/single.md/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_rename_file(self) -> None:
        self._create("fr", body="hi", files=[{"path": "a.md", "content": "alpha"}])
        # Get the file id via the detail view.
        before = self.client.get(f"{self.base_url}name/fr/").json()
        assert before["files"][0]["path"] == "a.md"
        res = self.client.post(
            f"{self.base_url}name/fr/files-rename/",
            data={"from_path": "a.md", "to_path": "renamed.md"},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_200_OK, res.content
        after = self.client.get(f"{self.base_url}name/fr/").json()
        assert after["files"][0]["path"] == "renamed.md"

    # ---- Validation ----

    def test_canonical_name_rejected_for_team_create(self) -> None:
        res = self.client.post(
            self.base_url,
            data={"name": "@posthog/illegal", "body": "x"},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_slug_rejected(self) -> None:
        res = self.client.post(
            self.base_url,
            data={"name": "Bad Name!", "body": "x"},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_duplicate_name_rejected(self) -> None:
        self._create("dup")
        res = self.client.post(
            self.base_url,
            data={"name": "dup", "body": "again"},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    # ---- Helpers ----

    def _create(self, name: str, body: str = "x", files: list[dict] | None = None) -> dict:
        payload: dict = {"name": name, "body": body}
        if files is not None:
            payload["files"] = files
        res = self.client.post(self.base_url, data=payload, content_type="application/json")
        assert res.status_code == status.HTTP_201_CREATED, res.content
        return res.json()

    def _publish(self, name: str, body: str) -> Any:
        res = self.client.post(
            f"{self.base_url}name/{name}/publish/",
            data={"body": body},
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_200_OK, res.content
        return res
