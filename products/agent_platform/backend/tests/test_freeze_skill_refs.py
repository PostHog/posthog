from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from rest_framework.test import APIClient

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

from ..logic.janitor_client import JanitorClientError
from ..logic.kernel_skills import KernelSkill
from ..models import AgentApplication, AgentRevision


class TestFreezeResolvesSkillRefs(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="triage-helper",
            description="Decide which inbound tickets need a human.",
            body="The triage body.",
        )
        LLMSkillFile.objects.create(skill=self.skill, path="references/api.md", content="# API")
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id, slug="freeze-agent", name="Freeze agent", description=""
        )
        self.revision = AgentRevision.all_teams.create(
            application=self.application,
            spec={"model": "x", "triggers": []},
            skill_refs=[{"from_template": "triage-helper", "alias": "triage"}],
            state="draft",
            bundle_uri="fs://test/",
        )
        self.url = (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{self.revision.id}/freeze/"
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_materializes_skill_and_stamps_provenance(self, mock_janitor: MagicMock) -> None:
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.manifest.return_value = {"files": [{"path": "agent.md"}]}
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            "derived_spec": {
                "model": "x",
                "triggers": [],
                "skills": [{"id": "triage", "path": "skills/triage/SKILL.md", "description": "d"}],
                "tools": [],
            },
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)

        # The store skill was materialized into the bundle via the janitor with
        # the rendered SKILL.md (frontmatter + body) and its companion file.
        client.put_skill.assert_called_once()
        call_rev, call_alias, payload = client.put_skill.call_args.args
        self.assertEqual(call_rev, str(self.revision.id))
        self.assertEqual(call_alias, "triage")
        self.assertIn("name: triage-helper", payload["body"])
        self.assertIn("The triage body.", payload["body"])
        self.assertEqual(payload["files"], [{"path": "references/api.md", "content": "# API"}])

        # The frozen spec records provenance back to the pinned store version.
        self.revision.refresh_from_db()
        frozen_skill = self.revision.spec["skills"][0]
        self.assertEqual(frozen_skill["from_template"], "triage-helper")
        self.assertEqual(frozen_skill["version"], 1)
        self.assertEqual(frozen_skill["source_version_id"], str(self.skill.id))
        self.assertEqual(self.revision.state, "ready")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_fails_loud_on_missing_skill(self, mock_janitor: MagicMock) -> None:
        self.revision.skill_refs = [{"from_template": "ghost", "alias": "g"}]
        self.revision.save(update_fields=["skill_refs"])

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 400, res.content)
        mock_janitor.return_value.freeze.assert_not_called()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_sweeps_stale_skill_aliases(self, mock_janitor: MagicMock) -> None:
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.delete_skill = MagicMock(return_value={"ok": True})
        # A prior freeze materialized `skills/old/` from a store ref (its carried
        # spec entry keeps server-stamped `source_version_id` provenance); the
        # author has since dropped it from refs, leaving just `triage`, so `old`
        # must be swept.
        self.revision.spec = {
            "model": "x",
            "triggers": [],
            "skills": [{"id": "old", "path": "skills/old/SKILL.md", "source_version_id": "019e0000-0000-0000"}],
        }
        self.revision.save(update_fields=["spec"])
        client.manifest.return_value = {
            "files": [{"path": "agent.md"}, {"path": "skills/old/SKILL.md"}, {"path": "skills/triage/SKILL.md"}]
        }
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            "derived_spec": {"model": "x", "triggers": [], "skills": [], "tools": []},
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        client.delete_skill.assert_called_once_with(str(self.revision.id), "old")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_fails_loud_on_legacy_inline_skill(self, mock_janitor: MagicMock) -> None:
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.delete_skill = MagicMock(return_value={"ok": True})
        # Models a pre-store agent forked + re-frozen: the carried spec lists an
        # inline skill with no `from_template` provenance and no backing ref. The
        # freeze must refuse rather than silently strip it. (Detected from the
        # spec, the stable authoring record — not the volatile bundle.)
        self.revision.skill_refs = []
        self.revision.spec = {
            "model": "x",
            "triggers": [],
            "skills": [{"id": "legacy", "path": "skills/legacy/SKILL.md"}],
        }
        self.revision.save(update_fields=["skill_refs", "spec"])

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("legacy", str(res.content))
        # Fail loud BEFORE any destructive janitor call or seal.
        client.delete_skill.assert_not_called()
        client.freeze.assert_not_called()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_legacy_guard_not_bypassed_by_spoofed_from_template(self, mock_janitor: MagicMock) -> None:
        client = mock_janitor.return_value
        client.delete_skill = MagicMock(return_value={"ok": True})
        # `from_template` is author-writable on a draft spec, so an attacker could
        # add a fake one to a legacy inline entry to slip it past the guard and have
        # the sweep silently drop it. The discriminant is the server-only
        # `source_version_id`, which the write schema rejects — so the spoof still
        # refuses.
        self.revision.skill_refs = []
        self.revision.spec = {
            "model": "x",
            "triggers": [],
            "skills": [{"id": "legacy", "path": "skills/legacy/SKILL.md", "from_template": "spoofed"}],
        }
        self.revision.save(update_fields=["skill_refs", "spec"])

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("legacy", str(res.content))
        client.delete_skill.assert_not_called()
        client.freeze.assert_not_called()

    @staticmethod
    def _kernel(skill_id: str) -> KernelSkill:
        body = f"---\nname: {skill_id}\ndescription: {skill_id} desc\nagents:\n- freeze-agent\n---\n\n# {skill_id}"
        return KernelSkill(id=skill_id, description=f"{skill_id} desc", body=body, agents=frozenset({"freeze-agent"}))

    @patch("products.agent_platform.backend.presentation.views.kernel_skills_for")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_injects_kernel_skills_alongside_store_refs(
        self, mock_janitor: MagicMock, mock_kernel: MagicMock
    ) -> None:
        # A designated agent's kernel skills (platform code) materialize at freeze
        # next to the resolved store ref — both land in `skills/` via the janitor,
        # and the kernel body keeps its frontmatter so freeze derives its description.
        mock_kernel.return_value = [self._kernel("safety-and-boundaries")]
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.delete_skill = MagicMock(return_value={"ok": True})
        client.manifest.return_value = {"files": [{"path": "agent.md"}]}
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            "derived_spec": {
                "model": "x",
                "triggers": [],
                "skills": [
                    {"id": "triage", "path": "skills/triage/SKILL.md", "description": "d"},
                    {
                        "id": "safety-and-boundaries",
                        "path": "skills/safety-and-boundaries/SKILL.md",
                        "description": "k",
                    },
                ],
                "tools": [],
            },
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        # Kernel selection keys on the agent's slug — pin the call arg so swapping
        # the call site to anything else can't silently disable kernel injection.
        mock_kernel.assert_called_once_with(self.application.slug)
        materialized = {call.args[1] for call in client.put_skill.call_args_list}
        self.assertEqual(materialized, {"triage", "safety-and-boundaries"})
        kernel_call = next(c for c in client.put_skill.call_args_list if c.args[1] == "safety-and-boundaries")
        self.assertIn("name: safety-and-boundaries", kernel_call.args[2]["body"])

    @patch("products.agent_platform.backend.presentation.views.kernel_skills_for")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_does_not_sweep_kernel_skill_folder(self, mock_janitor: MagicMock, mock_kernel: MagicMock) -> None:
        # The kernel folder is in the bundle but backed by no store ref — the sweep
        # must keep it (it's platform-injected, not a removed-ref leftover) while
        # still sweeping a genuine orphan.
        mock_kernel.return_value = [self._kernel("safety-and-boundaries")]
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.delete_skill = MagicMock(return_value={"ok": True})
        client.manifest.return_value = {
            "files": [
                {"path": "agent.md"},
                {"path": "skills/safety-and-boundaries/SKILL.md"},
                {"path": "skills/stale/SKILL.md"},
                {"path": "skills/triage/SKILL.md"},
            ]
        }
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            # The sealed spec carries the injected kernel skill (the freeze asserts
            # every kernel id materialized before flipping to ready).
            "derived_spec": {
                "model": "x",
                "triggers": [],
                "skills": [{"id": "safety-and-boundaries", "path": "skills/safety-and-boundaries/SKILL.md"}],
                "tools": [],
            },
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        mock_kernel.assert_called_once_with(self.application.slug)
        swept = {call.args[1] for call in client.delete_skill.call_args_list}
        self.assertEqual(swept, {"stale"})

    @patch("products.agent_platform.backend.presentation.views.kernel_skills_for")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_rejects_kernel_id_colliding_with_store_alias(
        self, mock_janitor: MagicMock, mock_kernel: MagicMock
    ) -> None:
        # A kernel skill id that collides with a store ref alias is ambiguous — both
        # would target `skills/triage/`. Refuse before any janitor write.
        mock_kernel.return_value = [self._kernel("triage")]
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("collide", str(res.content))
        mock_kernel.assert_called_once_with(self.application.slug)
        client.freeze.assert_not_called()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    @patch("products.agent_platform.backend.presentation.views.kernel_skills_for")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_exempts_kernel_skill_from_legacy_orphan_guard(
        self, mock_janitor: MagicMock, mock_kernel: MagicMock
    ) -> None:
        # A forked spec carries an inline kernel entry (no `source_version_id`, no
        # backing ref). The legacy-orphan guard would refuse it as pre-store content,
        # but it's a current kernel skill — freeze must accept and re-inject it.
        mock_kernel.return_value = [self._kernel("safety-and-boundaries")]
        self.revision.skill_refs = []
        self.revision.spec = {
            "model": "x",
            "triggers": [],
            "skills": [{"id": "safety-and-boundaries", "path": "skills/safety-and-boundaries/SKILL.md"}],
        }
        self.revision.save(update_fields=["skill_refs", "spec"])
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.delete_skill = MagicMock(return_value={"ok": True})
        client.manifest.return_value = {"files": [{"path": "skills/safety-and-boundaries/SKILL.md"}]}
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            "derived_spec": {
                "model": "x",
                "triggers": [],
                "skills": [{"id": "safety-and-boundaries", "path": "skills/safety-and-boundaries/SKILL.md"}],
                "tools": [],
            },
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        mock_kernel.assert_called_once_with(self.application.slug)
        client.freeze.assert_called_once()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "ready")

    @patch("products.agent_platform.backend.presentation.views.all_kernel_skill_ids")
    @patch("products.agent_platform.backend.presentation.views.kernel_skills_for")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_drops_inline_kernel_entry_no_kernel_targets_this_agent(
        self, mock_janitor: MagicMock, mock_kernel: MagicMock, mock_all_kernel_ids: MagicMock
    ) -> None:
        # A cross-team `clone_from` of an agent-builder revision lands an opaque slug
        # no kernel skill targets, but the carried spec still has the inline kernel
        # entry (no `source_version_id`, no backing ref). It's a shipped kernel id, so
        # the legacy-orphan guard must let the freeze through and the sweep must drop
        # the now-inapplicable folder — not brick the fork permanently.
        mock_kernel.return_value = []
        mock_all_kernel_ids.return_value = frozenset({"safety-and-boundaries"})
        self.revision.skill_refs = []
        self.revision.spec = {
            "model": "x",
            "triggers": [],
            "skills": [{"id": "safety-and-boundaries", "path": "skills/safety-and-boundaries/SKILL.md"}],
        }
        self.revision.save(update_fields=["skill_refs", "spec"])
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.delete_skill = MagicMock(return_value={"ok": True})
        client.manifest.return_value = {"files": [{"path": "skills/safety-and-boundaries/SKILL.md"}]}
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            "derived_spec": {"model": "x", "triggers": [], "skills": [], "tools": []},
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        client.delete_skill.assert_called_once_with(str(self.revision.id), "safety-and-boundaries")
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "ready")

    @patch("products.agent_platform.backend.presentation.views.kernel_skills_for")
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_retry_on_sealed_bundle_does_not_wedge_on_kernel_drift(
        self, mock_janitor: MagicMock, mock_kernel: MagicMock
    ) -> None:
        # A prior freeze sealed the bundle (response lost); the kernel set has since
        # grown, so the sealed spec can't contain the newer kernel id. The retry hits
        # a sealed-bundle 409, falls through to the idempotent freeze, and must NOT
        # re-apply the post-seal kernel invariant against the immutable sealed bytes —
        # otherwise every retry wedges the draft forever.
        mock_kernel.return_value = [self._kernel("safety-and-boundaries")]
        client = mock_janitor.return_value
        client.manifest.return_value = {"files": [{"path": "skills/triage/SKILL.md"}]}
        client.put_skill = MagicMock(
            side_effect=JanitorClientError(409, "revision_not_draft", body={"error": "revision_not_draft"})
        )
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            # Sealed bytes predate the kernel skill — it can't appear here.
            "derived_spec": {
                "model": "x",
                "triggers": [],
                "skills": [{"id": "triage", "path": "skills/triage/SKILL.md"}],
                "tools": [],
            },
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        client.freeze.assert_called_once()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "ready")

    @property
    def _detail_url(self) -> str:
        return f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/revisions/{self.revision.id}/"

    def test_spec_write_preserves_server_skills_and_round_trips_source_version_id(self) -> None:
        # A forked draft carries server-derived skills[] (with the stamped, write-schema
        # -rejected `source_version_id`). Editing an unrelated spec field must NOT 400,
        # and an author can't change/spoof skills[] — it's pinned to the server value.
        self.revision.spec = {
            "model": "faux/old",
            "triggers": [],
            "skills": [{"id": "triage", "path": "skills/triage/SKILL.md", "source_version_id": "019e-real"}],
        }
        self.revision.save(update_fields=["spec"])

        res = self.client.patch(
            self._detail_url,
            {
                "spec": {
                    "models": {"mode": "manual", "models": [{"model": "faux/new"}]},
                    "triggers": [],
                    # Author attempt to inject/spoof a skill — must be ignored.
                    "skills": [{"id": "evil", "path": "skills/evil/SKILL.md", "source_version_id": "019e-fake"}],
                }
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.spec["models"]["models"][0]["model"], "faux/new")
        # skills[] is the preserved server value, not the author's spoof.
        self.assertEqual([s["id"] for s in self.revision.spec["skills"]], ["triage"])
        self.assertEqual(self.revision.spec["skills"][0]["source_version_id"], "019e-real")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_tolerates_404_when_sweeping_a_skill_md_less_folder(self, mock_janitor: MagicMock) -> None:
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        # A stale companion-only folder has no SKILL.md, so the janitor 404s on delete.
        # The sweep must treat that as already-gone, not wedge the freeze.
        client.delete_skill = MagicMock(side_effect=JanitorClientError(404, "skill_not_found", body={}))
        client.manifest.return_value = {
            "files": [{"path": "skills/triage/SKILL.md"}, {"path": "skills/ghost/references/x.md"}]
        }
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            "derived_spec": {"model": "x", "triggers": [], "skills": [], "tools": []},
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        client.delete_skill.assert_called_once_with(str(self.revision.id), "ghost")
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "ready")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_pins_unpinned_ref_version_back_into_skill_refs(self, mock_janitor: MagicMock) -> None:
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.delete_skill = MagicMock(return_value={"ok": True})
        client.manifest.return_value = {"files": [{"path": "agent.md"}]}
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            "derived_spec": {"model": "x", "triggers": [], "skills": [], "tools": []},
        }
        # The default ref omits `version` (tracks latest). After freeze the row's
        # skill_refs must carry the resolved version + source_version_id so a fork
        # inherits a concrete pin instead of re-resolving latest.
        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        pinned = self.revision.skill_refs[0]
        self.assertEqual(pinned["from_template"], "triage-helper")
        self.assertEqual(pinned["version"], self.skill.version)
        self.assertEqual(pinned["source_version_id"], str(self.skill.id))

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_sweeps_leftover_folder_without_misclassifying_as_legacy(self, mock_janitor: MagicMock) -> None:
        client = mock_janitor.return_value
        client.put_skill = MagicMock(return_value={"ok": True})
        client.delete_skill = MagicMock(return_value={"ok": True})
        # A `skills/leftover/` folder from a prior *failed* freeze is in the bundle
        # but NOT in the spec (the failed attempt never saved derived_spec). It must
        # be swept on retry, not misclassified as a legacy inline skill and refused.
        client.manifest.return_value = {
            "files": [{"path": "agent.md"}, {"path": "skills/leftover/SKILL.md"}, {"path": "skills/triage/SKILL.md"}]
        }
        client.freeze.return_value = {
            "bundle_sha256": "a" * 64,
            "derived_spec": {"model": "x", "triggers": [], "skills": [], "tools": []},
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        client.delete_skill.assert_called_once_with(str(self.revision.id), "leftover")
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "ready")

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_short_circuits_on_already_sealed_bundle(self, mock_janitor: MagicMock) -> None:
        client = mock_janitor.return_value
        # A prior freeze sealed the bundle but its HTTP response was lost; the row
        # is still draft. On retry, the janitor refuses edits (409 revision_not_draft)
        # — freeze must skip materialization and stamp from the idempotent freeze.
        client.manifest.return_value = {"files": [{"path": "skills/triage/SKILL.md"}]}
        client.delete_skill = MagicMock(return_value={"ok": True})
        client.put_skill = MagicMock(
            side_effect=JanitorClientError(409, "sealed", body={"error": "revision_not_draft", "state": "ready"})
        )
        client.freeze.return_value = {
            "bundle_sha256": "b" * 64,
            "idempotent": True,
            "derived_spec": {
                "model": "x",
                "triggers": [],
                "skills": [{"id": "triage", "path": "skills/triage/SKILL.md", "description": "d"}],
                "tools": [],
            },
        }

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 200, res.content)
        client.freeze.assert_called_once_with(str(self.revision.id))
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "ready")
        self.assertEqual(self.revision.bundle_sha256, "b" * 64)

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_freeze_rejects_more_than_max_skill_refs(self, mock_janitor: MagicMock) -> None:
        # The serializer caps refs at 50, but fork / raw write can smuggle more into
        # the column — freeze must re-bound the count before fanning out.
        self.revision.skill_refs = [{"from_template": "triage-helper", "alias": f"a{i}"} for i in range(51)]
        self.revision.save(update_fields=["skill_refs"])

        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 400, res.content)
        mock_janitor.return_value.freeze.assert_not_called()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    @property
    def _skill_refs_url(self) -> str:
        return (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{self.revision.id}/skill_refs/"
        )

    def test_set_skill_refs_replaces_the_list(self) -> None:
        res = self.client.put(
            self._skill_refs_url,
            {
                "skill_refs": [
                    {"from_template": "triage-helper", "alias": "a"},
                    {"from_template": "triage-helper", "alias": "b", "version": 2},
                ]
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        self.assertEqual([r["alias"] for r in self.revision.skill_refs], ["a", "b"])
        self.assertEqual(self.revision.skill_refs[1]["version"], 2)

    def test_set_skill_refs_rejects_duplicate_alias(self) -> None:
        res = self.client.put(
            self._skill_refs_url,
            {"skill_refs": [{"from_template": "x", "alias": "dup"}, {"from_template": "y", "alias": "dup"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content)

    def test_set_skill_refs_blocked_on_non_draft(self) -> None:
        self.revision.state = "ready"
        self.revision.save(update_fields=["state"])
        res = self.client.put(
            self._skill_refs_url,
            {"skill_refs": [{"from_template": "triage-helper", "alias": "a"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content)

    def _bearer_client(self, scopes: list[str]) -> APIClient:
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="agent-key", user=self.user, secure_value=hash_key_value(raw), scopes=scopes
        )
        client = APIClient()  # no session — only the Bearer token authenticates
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        return client

    def test_freeze_denied_for_token_without_llm_skill_read(self) -> None:
        # A token with agents:write but no llm_skill:read must not be able to
        # materialize (and thus read) store-skill content via the bundle.
        client = self._bearer_client(["agents:read", "agents:write"])
        res = client.post(self.url)
        self.assertEqual(res.status_code, 403, res.content)
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.state, "draft")

    def test_set_skill_refs_denied_for_token_without_llm_skill_read(self) -> None:
        client = self._bearer_client(["agents:read", "agents:write"])
        res = client.put(
            self._skill_refs_url,
            {"skill_refs": [{"from_template": "triage-helper", "alias": "a"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 403, res.content)

    def test_set_skill_refs_allowed_for_token_with_llm_skill_read(self) -> None:
        client = self._bearer_client(["agents:read", "agents:write", "llm_skill:read"])
        res = client.put(
            self._skill_refs_url,
            {"skill_refs": [{"from_template": "triage-helper", "alias": "a"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.revision.refresh_from_db()
        self.assertEqual([r["alias"] for r in self.revision.skill_refs], ["a"])
