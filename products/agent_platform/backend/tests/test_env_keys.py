"""
Tests for the per-key env management endpoints on AgentApplicationViewSet.

Covers list / status / set / clear without ever returning decrypted
values across the wire, and verifies that merging behaviour preserves
unrelated keys.
"""

from __future__ import annotations

import json

from posthog.test.base import APIBaseTest

from ..models import AgentApplication


class TestAgentApplicationEnvKeys(APIBaseTest):
    databases = {
        "default",
        "persons_db_writer",
        "persons_db_reader",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def _app(self) -> AgentApplication:
        app = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="secrets-agent",
            name="Secrets agent",
            description="",
        )
        # Seed two existing keys so we can verify merges don't wipe siblings.
        app.encrypted_env = json.dumps({"ANTHROPIC_KEY": "sk-old", "SLACK_TOKEN": "xoxb-old"})
        app.save(update_fields=["encrypted_env"])
        return app

    def _url(self, app: AgentApplication, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.slug}/{suffix}"

    def test_list_returns_keys_sorted_no_values(self) -> None:
        app = self._app()
        res = self.client.get(self._url(app, "env_keys/"))
        assert res.status_code == 200, res.content
        body = res.json()
        assert body == {"keys": ["ANTHROPIC_KEY", "SLACK_TOKEN"]}
        # Defensively check no value leaks into the response.
        assert "sk-old" not in res.content.decode()
        assert "xoxb-old" not in res.content.decode()

    def test_list_on_unset_env_returns_empty(self) -> None:
        app = AgentApplication.all_teams.create(team_id=self.team.id, slug="fresh-agent", name="Fresh", description="")
        res = self.client.get(self._url(app, "env_keys/"))
        assert res.status_code == 200
        assert res.json() == {"keys": []}

    def test_per_key_get_reports_status_no_value(self) -> None:
        app = self._app()
        res = self.client.get(self._url(app, "env_keys/ANTHROPIC_KEY/"))
        assert res.status_code == 200
        assert res.json() == {"key": "ANTHROPIC_KEY", "is_set": True}

        res = self.client.get(self._url(app, "env_keys/UNSET_KEY/"))
        assert res.status_code == 200
        assert res.json() == {"key": "UNSET_KEY", "is_set": False}

    def test_put_upserts_one_key_and_preserves_siblings(self) -> None:
        app = self._app()
        res = self.client.put(
            self._url(app, "env_keys/NEW_KEY/"),
            data={"value": "new-secret"},
            content_type="application/json",
        )
        assert res.status_code == 200, res.content
        assert res.json() == {"key": "NEW_KEY", "is_set": True}

        app.refresh_from_db()
        stored = json.loads(app.encrypted_env)
        assert stored == {
            "ANTHROPIC_KEY": "sk-old",
            "SLACK_TOKEN": "xoxb-old",
            "NEW_KEY": "new-secret",
        }

    def test_put_rotates_existing_key(self) -> None:
        app = self._app()
        res = self.client.put(
            self._url(app, "env_keys/ANTHROPIC_KEY/"),
            data={"value": "sk-rotated"},
            content_type="application/json",
        )
        assert res.status_code == 200
        app.refresh_from_db()
        stored = json.loads(app.encrypted_env)
        assert stored["ANTHROPIC_KEY"] == "sk-rotated"
        # Siblings untouched.
        assert stored["SLACK_TOKEN"] == "xoxb-old"

    def test_delete_removes_one_key_and_preserves_siblings(self) -> None:
        app = self._app()
        res = self.client.delete(self._url(app, "env_keys/ANTHROPIC_KEY/"))
        assert res.status_code == 200
        assert res.json() == {"key": "ANTHROPIC_KEY", "is_set": False}

        app.refresh_from_db()
        stored = json.loads(app.encrypted_env)
        assert stored == {"SLACK_TOKEN": "xoxb-old"}

    def test_delete_unset_key_is_idempotent(self) -> None:
        app = self._app()
        res = self.client.delete(self._url(app, "env_keys/NEVER_SET/"))
        assert res.status_code == 200
        assert res.json() == {"key": "NEVER_SET", "is_set": False}
        app.refresh_from_db()
        # Original siblings untouched.
        assert json.loads(app.encrypted_env) == {
            "ANTHROPIC_KEY": "sk-old",
            "SLACK_TOKEN": "xoxb-old",
        }

    def test_put_rejects_when_value_missing(self) -> None:
        app = self._app()
        res = self.client.put(
            self._url(app, "env_keys/X/"),
            data={},
            content_type="application/json",
        )
        assert res.status_code == 400

    def test_put_allows_blank_value(self) -> None:
        """Blank values are valid — some integrations use empty strings as
        an explicit "clear, but keep the key registered" marker."""
        app = self._app()
        res = self.client.put(
            self._url(app, "env_keys/BLANK/"),
            data={"value": ""},
            content_type="application/json",
        )
        assert res.status_code == 200
        app.refresh_from_db()
        assert json.loads(app.encrypted_env)["BLANK"] == ""

    def test_list_recovers_from_corrupt_env_block(self) -> None:
        app = AgentApplication.all_teams.create(team_id=self.team.id, slug="corrupt", name="Corrupt", description="")
        # Simulate a corrupt env block — historic bug or manual tampering.
        app.encrypted_env = "not json"
        app.save(update_fields=["encrypted_env"])

        res = self.client.get(self._url(app, "env_keys/"))
        assert res.status_code == 200
        assert res.json() == {"keys": []}
