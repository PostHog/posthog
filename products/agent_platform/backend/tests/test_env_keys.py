"""
Tests for the per-key env management endpoints on AgentRevisionViewSet.

Secrets live on the revision (each revision runs against its own
`encrypted_env`), so these endpoints are nested under a revision. Covers list /
status / set / clear without ever returning decrypted values across the wire,
verifies merges preserve unrelated keys, and that editing one revision's env
never touches another's.
"""

from __future__ import annotations

import json
from typing import Any

from posthog.test.base import APIBaseTest

from ..models import AgentApplication, AgentRevision


class TestAgentRevisionEnvKeys(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def _app(self, slug: str = "secrets-agent") -> AgentApplication:
        return AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug=slug,
            name="Secrets agent",
            description="",
        )

    def _revision(self, app: AgentApplication, env: dict[str, Any] | None = None) -> AgentRevision:
        rev = AgentRevision.all_teams.create(
            application=app,
            team_id=app.team_id,
            state="draft",
            bundle_uri=f"local://{app.slug}/v1",
            spec={"model": "anthropic/claude-sonnet-4-6"},
        )
        if env is not None:
            # EncryptedTextField encrypts on assignment+save.
            rev.encrypted_env = json.dumps(env)
            rev.save(update_fields=["encrypted_env"])
        return rev

    def _seeded(self) -> tuple[AgentApplication, AgentRevision]:
        app = self._app()
        # Seed two existing keys so we can verify merges don't wipe siblings.
        rev = self._revision(app, {"ANTHROPIC_KEY": "sk-old", "SLACK_TOKEN": "xoxb-old"})
        return app, rev

    def _url(self, app: AgentApplication, rev: AgentRevision, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{app.slug}/revisions/{rev.id}/{suffix}"

    def test_list_returns_keys_sorted_no_values(self) -> None:
        app, rev = self._seeded()
        res = self.client.get(self._url(app, rev, "env_keys/"))
        assert res.status_code == 200, res.content
        body = res.json()
        assert body == {"keys": ["ANTHROPIC_KEY", "SLACK_TOKEN"]}
        # Defensively check no value leaks into the response.
        assert "sk-old" not in res.content.decode()
        assert "xoxb-old" not in res.content.decode()

    def test_list_on_unset_env_returns_empty(self) -> None:
        app = self._app("fresh-agent")
        rev = self._revision(app)
        res = self.client.get(self._url(app, rev, "env_keys/"))
        assert res.status_code == 200
        assert res.json() == {"keys": []}

    def test_per_key_get_reports_status_no_value(self) -> None:
        app, rev = self._seeded()
        res = self.client.get(self._url(app, rev, "env_keys/ANTHROPIC_KEY/"))
        assert res.status_code == 200
        assert res.json() == {"key": "ANTHROPIC_KEY", "is_set": True}

        res = self.client.get(self._url(app, rev, "env_keys/UNSET_KEY/"))
        assert res.status_code == 200
        assert res.json() == {"key": "UNSET_KEY", "is_set": False}

    def test_put_upserts_one_key_and_preserves_siblings(self) -> None:
        app, rev = self._seeded()
        res = self.client.put(
            self._url(app, rev, "env_keys/NEW_KEY/"),
            data={"value": "new-secret"},
            content_type="application/json",
        )
        assert res.status_code == 200, res.content
        assert res.json() == {"key": "NEW_KEY", "is_set": True}

        rev.refresh_from_db()
        stored = json.loads(rev.encrypted_env)
        assert stored == {
            "ANTHROPIC_KEY": "sk-old",
            "SLACK_TOKEN": "xoxb-old",
            "NEW_KEY": "new-secret",
        }

    def test_put_allowed_on_live_revision(self) -> None:
        """Editing secrets is allowed in ANY state — rotating a key on a live
        revision must not require cutting a new one (spec edits stay draft-only,
        secrets are operational)."""
        app, rev = self._seeded()
        rev.state = "live"
        rev.save(update_fields=["state"])
        res = self.client.put(
            self._url(app, rev, "env_keys/ANTHROPIC_KEY/"),
            data={"value": "sk-rotated"},
            content_type="application/json",
        )
        assert res.status_code == 200, res.content
        rev.refresh_from_db()
        # Rotating an existing key must replace just that key — sibling keys
        # are a separate codepath in the merge (update vs insert) and the
        # upserts-and-preserves-siblings test only covers the insert case.
        assert json.loads(rev.encrypted_env) == {
            "ANTHROPIC_KEY": "sk-rotated",
            "SLACK_TOKEN": "xoxb-old",
        }

    def test_delete_removes_one_key_and_preserves_siblings(self) -> None:
        app, rev = self._seeded()
        res = self.client.delete(self._url(app, rev, "env_keys/ANTHROPIC_KEY/"))
        assert res.status_code == 200
        assert res.json() == {"key": "ANTHROPIC_KEY", "is_set": False}

        rev.refresh_from_db()
        assert json.loads(rev.encrypted_env) == {"SLACK_TOKEN": "xoxb-old"}

    def test_delete_unset_key_is_idempotent(self) -> None:
        """`pop(key, None)` is a no-op when the key isn't there — DELETE on a
        never-set key still returns the standard `{is_set: False}` shape and
        leaves every other key untouched."""
        app, rev = self._seeded()
        res = self.client.delete(self._url(app, rev, "env_keys/NEVER_SET/"))
        assert res.status_code == 200
        assert res.json() == {"key": "NEVER_SET", "is_set": False}

        rev.refresh_from_db()
        assert json.loads(rev.encrypted_env) == {
            "ANTHROPIC_KEY": "sk-old",
            "SLACK_TOKEN": "xoxb-old",
        }

    def test_editing_one_revision_does_not_touch_another(self) -> None:
        app = self._app()
        rev_a = self._revision(app, {"SHARED": "a-value"})
        rev_b = self._revision(app, {"SHARED": "b-value"})
        res = self.client.put(
            self._url(app, rev_a, "env_keys/SHARED/"),
            data={"value": "a-rotated"},
            content_type="application/json",
        )
        assert res.status_code == 200
        rev_a.refresh_from_db()
        rev_b.refresh_from_db()
        assert json.loads(rev_a.encrypted_env)["SHARED"] == "a-rotated"
        # The sibling revision is untouched — secrets are per-revision.
        assert json.loads(rev_b.encrypted_env)["SHARED"] == "b-value"

    def test_set_env_replaces_whole_block(self) -> None:
        app, rev = self._seeded()
        res = self.client.post(
            self._url(app, rev, "set_env/"),
            data={"env": {"ONLY_KEY": "only-value"}},
            content_type="application/json",
        )
        assert res.status_code == 200, res.content
        rev.refresh_from_db()
        assert json.loads(rev.encrypted_env) == {"ONLY_KEY": "only-value"}

    def test_put_rejects_when_value_missing(self) -> None:
        app, rev = self._seeded()
        res = self.client.put(
            self._url(app, rev, "env_keys/X/"),
            data={},
            content_type="application/json",
        )
        assert res.status_code == 400

    def test_put_allows_blank_value(self) -> None:
        """Blank values are valid — some integrations use empty strings as
        an explicit "clear, but keep the key registered" marker."""
        app, rev = self._seeded()
        res = self.client.put(
            self._url(app, rev, "env_keys/BLANK/"),
            data={"value": ""},
            content_type="application/json",
        )
        assert res.status_code == 200
        rev.refresh_from_db()
        assert json.loads(rev.encrypted_env)["BLANK"] == ""

    def test_list_recovers_from_corrupt_env_block(self) -> None:
        app = self._app("corrupt")
        rev = self._revision(app)
        # Simulate a corrupt env block — historic bug or manual tampering.
        rev.encrypted_env = "not json"
        rev.save(update_fields=["encrypted_env"])

        res = self.client.get(self._url(app, rev, "env_keys/"))
        assert res.status_code == 200
        assert res.json() == {"keys": []}
