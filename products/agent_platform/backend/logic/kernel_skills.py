"""Platform-defined *kernel* skills — code-locked operator behaviour the freeze
step injects into an agent's bundle, never authored through the API.

The store (`skill_refs` → the llma-skill store) is the **only** author path into
a bundle's `skills/`. Kernel skills are the platform's complement to that: they
must move in lockstep with the implementation and be identical across every
account, so they can't live in the DB (where a frozen agent could pin a stale
copy while the platform moved on) and they can't be author-authored (there is no
`skills` field on any author endpoint). The freeze step reads them from this
package and materializes them alongside the resolved store skills.

Everything is data-driven: each kernel skill is a folder under `kernel_skills/`
holding a `SKILL.md` whose YAML frontmatter carries its `description` and an
`agents` mapping declaring which agents receive it:

    ---
    name: safety-and-boundaries
    description: One line, <= 280 chars. The system-prompt index line; drives load-skill.
    agents: ["*"]          # every agent (the shared baseline), OR
    agents: [agent-builder] # only these slugs (a per-agent skill)
    ---

Adding a kernel skill is "drop a folder" — no code change here. The loader
validates aggressively at read time (see `_all_kernel_skills`) so a malformed
folder fails loudly at the first freeze rather than silently shipping a degraded
or absent skill (or wedging freeze mid-injection with an opaque janitor error).

NOTE: kernel selection keys on `revision.application.slug`. Per-slug skills are
safe to target by name only because human-readable slugs are gated behind a
first-party allowlist (`AGENT_PLATFORM_EXPLICIT_SLUG_TEAM_IDS`); normal teams get
opaque server-minted slugs and can't self-assign e.g. `agent-builder`. An
`agents: ["*"]` skill bypasses that gate and reaches EVERY agent — use it only
for genuinely universal platform content.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_KERNEL_SKILLS_DIR = Path(__file__).resolve().parent.parent / "kernel_skills"
# Frontmatter `agents` wildcard: the skill goes to every agent (the baseline).
_WILDCARD = "*"
# Mirror of the janitor's RESOURCE_ID_REGEX (agent-shared typed-bundle.ts) — the
# id must be a valid bundle folder name the janitor's skill PUT will accept.
_RESOURCE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$")
# The janitor caps a derived skill description at this length (deriveSkillDescription).
_DESCRIPTION_MAX = 280


@dataclass(frozen=True)
class KernelSkill:
    """A platform kernel skill resolved to its bundle-ready form. `agents` is the
    set of slugs it applies to, or `{"*"}` for every agent."""

    id: str
    description: str
    body: str
    agents: frozenset[str]

    def applies_to(self, slug: str) -> bool:
        return _WILDCARD in self.agents or slug in self.agents

    def put_skill_payload(self) -> dict:
        """Body for the janitor ``PUT /revisions/:id/skills/:id`` call — the same
        shape ``ResolvedSkill`` uses, so store and kernel skills materialize
        through one code path. `body` keeps its frontmatter, so the freeze
        derives the same `description` the index here reports (the loader
        enforces that parity)."""
        return {"description": self.description, "body": self.body, "files": []}


def _frontmatter_block(raw: str) -> str | None:
    """The YAML between the leading ``---`` fences, or None if not well-formed.
    Requires whole-line fences, matching the janitor's `splitFrontmatter`."""
    if not raw.startswith("---\n"):
        return None
    end = raw.find("\n---\n", len("---\n") - 1)
    if end == -1:
        return None
    return raw[len("---\n") : end + 1]


def _janitor_derived_description(block: str) -> str:
    """Replicate the janitor's freeze-time `deriveSkillDescription`: the value of
    the FIRST physical `description:` line (quotes stripped), capped at 280. This
    — not the full YAML scalar — is what lands in `spec.skills[].description` and
    drives the model's load decision, so the loader checks the file matches it."""
    for line in block.split("\n"):
        m = re.match(r"^description:\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip("\"'")[:_DESCRIPTION_MAX]
    return ""


def _all_kernel_skills() -> tuple[KernelSkill, ...]:
    # Not cached: re-reading a handful of small files per freeze (an authoring-time
    # action, not a hot path) keeps the set exactly in lockstep with what's on
    # disk, with no process-lifetime staleness window.
    skills: list[KernelSkill] = []
    for folder in sorted(p for p in _KERNEL_SKILLS_DIR.iterdir() if p.is_dir()):
        sid = folder.name
        md = folder / "SKILL.md"
        # Fail loud on a malformed folder — a silently-skipped or degraded kernel
        # skill is the dangerous case (e.g. a dropped safety skill). Mirrors the
        # stance the `agents` check below already takes.
        if not md.is_file():
            raise ValueError(f"kernel skill '{sid}' has no SKILL.md")
        if not _RESOURCE_ID_RE.match(sid) or len(sid) > 64:
            raise ValueError(f"kernel skill folder '{sid}' is not a valid skill id (lowercase/digits/-/_, <=64)")
        raw = md.read_text()
        block = _frontmatter_block(raw)
        if block is None:
            raise ValueError(f"kernel skill '{sid}' is missing a `---`-fenced YAML frontmatter block")
        fm = yaml.safe_load(block)
        if not isinstance(fm, dict):
            raise ValueError(f"kernel skill '{sid}' frontmatter is not a YAML mapping")

        description = str(fm.get("description") or "").strip()
        if not description:
            raise ValueError(f"kernel skill '{sid}' is missing a `description` frontmatter line")
        # The janitor re-derives the description from the body (single physical
        # line, <=280) and discards the payload value. If the file's `description`
        # spans multiple lines or exceeds the cap, the model would silently get a
        # truncated load signal — refuse it here so it fails at deploy, not freeze.
        if _janitor_derived_description(block) != description:
            raise ValueError(
                f"kernel skill '{sid}' description must be a single line of <= {_DESCRIPTION_MAX} chars "
                "(the freeze derivation reads only the first physical line)"
            )

        raw_agents = fm.get("agents")
        if isinstance(raw_agents, str):
            agents = [raw_agents]
        elif isinstance(raw_agents, list):
            agents = [str(a) for a in raw_agents]
        else:
            raise ValueError(f"kernel skill '{sid}' needs an `agents` frontmatter mapping (a slug list or \"*\")")
        if not agents:
            raise ValueError(f"kernel skill '{sid}' has an empty `agents` mapping — it would reach no agent")

        skills.append(KernelSkill(id=sid, description=description, body=raw, agents=frozenset(agents)))
    return tuple(skills)


def kernel_skills_for(slug: str) -> list[KernelSkill]:
    """The kernel skills an agent receives: every `*`-mapped skill (the baseline)
    plus those naming this slug. Empty for an agent no kernel skill targets."""
    return [k for k in _all_kernel_skills() if k.applies_to(slug)]
