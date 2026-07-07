"""
PUT  /revisions/<id>/bundle/file/    — single .md file update
POST /revisions/<id>/bundle/import/  — bulk import

Both wrap the typed bundle proxy (janitor). The janitor is mocked at the
client boundary; the cross-service path is covered by the agent-tests harness.
What we assert here is the Django-side contract: draft-only gating, path /
id validation, and that the per-skill writes carry the right description for
new vs existing rows.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from ..models import AgentApplication, AgentRevision


class TestBundleEditing(APIBaseTest):
    databases = {
        "default",
        "persons_db_writer",
        "persons_db_reader",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="growth-review",
            name="Growth review",
            description="",
        )

    def _revision(self, state: str = "draft") -> AgentRevision:
        return AgentRevision.all_teams.create(
            application=self.application,
            team_id=self.team.id,
            state=state,
            spec={},
            # `ready`/`live` rows in prod carry a stamped sha; supply one so the
            # row looks real even though we only need the state for the gate.
            bundle_sha256=("a" * 64) if state in {"ready", "live", "archived"} else None,
        )

    def _file_url(self, revision: AgentRevision) -> str:
        return (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{revision.id}/bundle/file/"
        )

    def _import_url(self, revision: AgentRevision) -> str:
        return (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{revision.id}/bundle/import/"
        )

    @staticmethod
    def _bundle_with_skills(*ids_and_descs: tuple[str, str]) -> dict:
        return {
            "bundle": {
                "agent_md": "",
                "skills": [{"id": i, "description": d, "body": ""} for i, d in ids_and_descs],
                "tools": [],
                "spec": {},
            },
        }

    # ── single-file PUT ────────────────────────────────────────────────────

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_agent_md_on_draft(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.put_agent_md.return_value = {"ok": True}

        res = self.client.put(
            self._file_url(revision),
            {"path": "agent.md", "content": "# New body"},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["id"], str(revision.id))
        mock_janitor.return_value.put_agent_md.assert_called_once_with(str(revision.id), "# New body")
        mock_janitor.return_value.put_skill.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_skill_body_on_draft(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.get_bundle.return_value = self._bundle_with_skills(
            ("growth-review", "Original description")
        )
        mock_janitor.return_value.put_skill.return_value = {"ok": True}

        res = self.client.put(
            self._file_url(revision),
            {"path": "skills/growth-review/SKILL.md", "content": "## Body"},
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        # Description must be preserved — it isn't supplied by this endpoint.
        mock_janitor.return_value.put_skill.assert_called_once_with(
            str(revision.id),
            "growth-review",
            {"description": "Original description", "body": "## Body"},
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_file_409_on_ready_live_archived(self, mock_janitor: MagicMock) -> None:
        for state in ("ready", "live", "archived"):
            with self.subTest(state=state):
                # Reset between iterations so assert_not_called() attributes
                # any leaked janitor call to the iteration that caused it
                # rather than the next one.
                mock_janitor.return_value.put_agent_md.reset_mock()
                mock_janitor.return_value.put_skill.reset_mock()
                revision = self._revision(state)
                res = self.client.put(
                    self._file_url(revision),
                    {"path": "agent.md", "content": "blocked"},
                    format="json",
                )
                self.assertEqual(res.status_code, 409, res.content)
                payload = res.json()
                self.assertEqual(payload["error"], "revision_not_draft")
                self.assertEqual(payload["state"], state)
                mock_janitor.return_value.put_agent_md.assert_not_called()
                mock_janitor.return_value.put_skill.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_file_rejects_tool_source_path(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        res = self.client.put(
            self._file_url(revision),
            {"path": "tools/foo/source.ts", "content": "export default {}"},
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content)
        mock_janitor.return_value.put_skill.assert_not_called()
        mock_janitor.return_value.put_agent_md.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_put_file_unknown_skill_id_returns_400(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.get_bundle.return_value = self._bundle_with_skills(("growth-review", "Original"))

        res = self.client.put(
            self._file_url(revision),
            {"path": "skills/never-added/SKILL.md", "content": "## Body"},
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content)
        mock_janitor.return_value.put_skill.assert_not_called()

    # ── bulk import ────────────────────────────────────────────────────────

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_mixes_new_and_existing_skill(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.get_bundle.return_value = self._bundle_with_skills(("existing", "Existing summary"))
        mock_janitor.return_value.put_agent_md.return_value = {"ok": True}
        mock_janitor.return_value.put_skill.return_value = {"ok": True}

        res = self.client.post(
            self._import_url(revision),
            {
                "agent_md": "# Top-level",
                "skills": [
                    {"id": "existing", "body": "updated body"},
                    {"id": "fresh-skill", "description": "Brand new", "body": "## Hello"},
                ],
            },
            format="json",
        )

        self.assertEqual(res.status_code, 200, res.content)
        mock_janitor.return_value.put_agent_md.assert_called_once_with(str(revision.id), "# Top-level")
        # Existing skill preserves the bundle description; new skill takes the payload's.
        mock_janitor.return_value.put_skill.assert_any_call(
            str(revision.id), "existing", {"description": "Existing summary", "body": "updated body"}
        )
        mock_janitor.return_value.put_skill.assert_any_call(
            str(revision.id), "fresh-skill", {"description": "Brand new", "body": "## Hello"}
        )
        self.assertEqual(mock_janitor.return_value.put_skill.call_count, 2)

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_409_on_ready_live_archived(self, mock_janitor: MagicMock) -> None:
        for state in ("ready", "live", "archived"):
            with self.subTest(state=state):
                # Reset between iterations so assert_not_called() attributes
                # any leaked janitor call to the iteration that caused it
                # rather than the next one.
                mock_janitor.return_value.put_agent_md.reset_mock()
                mock_janitor.return_value.put_skill.reset_mock()
                revision = self._revision(state)
                res = self.client.post(
                    self._import_url(revision),
                    {"agent_md": "blocked"},
                    format="json",
                )
                self.assertEqual(res.status_code, 409, res.content)
                self.assertEqual(res.json()["error"], "revision_not_draft")
                mock_janitor.return_value.put_agent_md.assert_not_called()
                mock_janitor.return_value.put_skill.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_rejects_bad_skill_id_format(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": "Has Spaces", "description": "x", "body": ""}]},
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content)
        # The whole request must be rejected before any upstream call lands —
        # otherwise a partial write would split the bundle mid-import.
        mock_janitor.return_value.put_skill.assert_not_called()
        mock_janitor.return_value.put_agent_md.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_new_skill_requires_description(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.get_bundle.return_value = self._bundle_with_skills()

        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": "new-skill", "body": "## Hi"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content)
        mock_janitor.return_value.put_skill.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_with_only_agent_md(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.put_agent_md.return_value = {"ok": True}

        res = self.client.post(
            self._import_url(revision),
            {"agent_md": "# Only this"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        mock_janitor.return_value.put_agent_md.assert_called_once_with(str(revision.id), "# Only this")
        mock_janitor.return_value.put_skill.assert_not_called()
        # No skills payload → no bundle fetch either.
        mock_janitor.return_value.get_bundle.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_with_empty_skills_array(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.put_agent_md.return_value = {"ok": True}

        res = self.client.post(
            self._import_url(revision),
            {"agent_md": "# Only this", "skills": []},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        mock_janitor.return_value.put_agent_md.assert_called_once_with(str(revision.id), "# Only this")
        mock_janitor.return_value.put_skill.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_import_with_only_skills(self, mock_janitor: MagicMock) -> None:
        revision = self._revision("draft")
        mock_janitor.return_value.get_bundle.return_value = self._bundle_with_skills(("kept", "Kept"))
        mock_janitor.return_value.put_skill.return_value = {"ok": True}

        res = self.client.post(
            self._import_url(revision),
            {"skills": [{"id": "kept", "body": "updated"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        # No agent_md key in payload → agent.md left alone.
        mock_janitor.return_value.put_agent_md.assert_not_called()
        mock_janitor.return_value.put_skill.assert_called_once_with(
            str(revision.id), "kept", {"description": "Kept", "body": "updated"}
        )
