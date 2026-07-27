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

Adding a kernel skill is "drop a folder."

Two read paths, deliberately split:
  - `_all_kernel_skills()` validates the **whole** shipped set strictly (raises on
    any malformation). It's exercised by a unit test, so a bad folder fails CI
    before merge.
  - `kernel_skills_for(slug)` is the **runtime** path. It only fully validates the
    folders that target the agent being frozen, and skips obvious non-skill
    directories — so a malformed folder for one agent can't take down freeze for
    every other tenant's agent.

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


def _normalize_agents(raw_agents: object) -> list[str]:
    """The `agents` frontmatter as a list of strings. A bare string becomes a
    one-element list; anything else (missing, number, mapping) becomes empty."""
    if isinstance(raw_agents, str):
        return [raw_agents]
    if isinstance(raw_agents, list):
        return [str(a) for a in raw_agents]
    return []


def _agents_of(folder: Path) -> list[str] | None:
    """Cheap read of just the `agents` mapping, for runtime applicability scoping.
    Returns None when it can't be determined — the runtime path then skips the
    folder rather than fully validating (and possibly raising on) a folder that
    doesn't even target the agent being frozen."""
    md = folder / "SKILL.md"
    if not md.is_file():
        return None
    # Force UTF-8: every shipped SKILL.md carries em dashes, and `read_text()`'s
    # locale default (e.g. ASCII under `LC_ALL=C`) would raise on the first folder
    # — taking down freeze for every agent, the exact blast radius this path avoids.
    block = _frontmatter_block(md.read_text(encoding="utf-8"))
    if block is None:
        return None
    try:
        fm = yaml.safe_load(block)
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    return _normalize_agents(fm.get("agents"))


def _load_skill(folder: Path) -> KernelSkill:
    """Strict load + validate. Raises ``ValueError`` on any malformation — a
    code-bundled set, so this is a deploy/CI-time fail-fast, not a runtime risk."""
    sid = folder.name
    md = folder / "SKILL.md"
    if not md.is_file():
        raise ValueError(f"kernel skill '{sid}' has no SKILL.md")
    if not _RESOURCE_ID_RE.match(sid) or len(sid) > 64:
        raise ValueError(f"kernel skill folder '{sid}' is not a valid skill id (lowercase/digits/-/_, <=64)")
    raw_bytes = md.read_bytes()
    # The janitor reads the raw bundle bytes from S3 (no universal-newline
    # translation), so a CR would leave its single-line `description:` derivation
    # holding a trailing `\r` that Python's parse never sees — a silent mismatch.
    # Require LF. Checked on the bytes because `read_text()` strips the CR.
    if b"\r" in raw_bytes:
        raise ValueError(f"kernel skill '{sid}' must use LF line endings (no CR)")
    raw = raw_bytes.decode("utf-8")
    block = _frontmatter_block(raw)
    if block is None:
        raise ValueError(f"kernel skill '{sid}' is missing a `---`-fenced YAML frontmatter block")
    try:
        fm = yaml.safe_load(block)
    except yaml.YAMLError as e:
        # Re-raise as ValueError so broken YAML joins the rest of the malformation
        # contract (`_all_kernel_skills`' CI check + the parameterized rejection tests).
        raise ValueError(f"kernel skill '{sid}' has invalid YAML frontmatter: {e}") from e
    if not isinstance(fm, dict):
        raise ValueError(f"kernel skill '{sid}' frontmatter is not a YAML mapping")

    description = str(fm.get("description") or "").strip()
    if not description:
        raise ValueError(f"kernel skill '{sid}' is missing a `description` frontmatter line")
    # The janitor re-derives the description from the body (single physical line,
    # <=280) and discards the payload value. If the file's `description` spans
    # multiple lines or exceeds the cap, the model would silently get a truncated
    # load signal — refuse it here so it fails at deploy, not freeze.
    if _janitor_derived_description(block) != description:
        raise ValueError(
            f"kernel skill '{sid}' description must be a single line of <= {_DESCRIPTION_MAX} chars "
            "(the freeze derivation reads only the first physical line)"
        )

    agents = _normalize_agents(fm.get("agents"))
    if not agents:
        raise ValueError(f"kernel skill '{sid}' needs an `agents` frontmatter mapping (a slug list or \"*\")")
    for a in agents:
        if a != _WILDCARD and not _RESOURCE_ID_RE.match(a):
            raise ValueError(f"kernel skill '{sid}' has an invalid agent slug {a!r} in its `agents` mapping")
    if _WILDCARD in agents and len(agents) > 1:
        raise ValueError(f"kernel skill '{sid}' mixes \"{_WILDCARD}\" with specific slugs — use one or the other")

    return KernelSkill(id=sid, description=description, body=raw, agents=frozenset(agents))


def _skill_dirs() -> list[Path]:
    """Candidate skill folders. Skips `.`/`_`-prefixed directories (editor/tooling
    cruft like `__pycache__` or `.DS_Store` dirs) so a stray directory can't wedge
    freeze — but keeps any letter/digit-named dir so a genuinely mis-named skill
    folder still trips `_load_skill`'s id check rather than vanishing silently."""
    # A deploy variant that ships the Django code without `kernel_skills/` must
    # degrade to "no kernel skills", not 500 every freeze on a missing-dir
    # `iterdir()`. The strict CI check (`_all_kernel_skills`) still guards the
    # in-repo set, so an accidentally-empty dir can't slip kernel skills out.
    if not _KERNEL_SKILLS_DIR.is_dir():
        return []
    return sorted(p for p in _KERNEL_SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def all_kernel_skill_ids() -> frozenset[str]:
    """Every shipped kernel skill id, across all `agents` mappings — a cheap,
    parse-free folder-name read (no malformation risk). Freeze uses this to tell
    platform-owned inline skill entries (a former/cross-team kernel id carried in a
    forked `spec.skills[]`) apart from genuine pre-store author content: the former
    is the platform's to drop and re-inject, the latter must block the freeze."""
    return frozenset(f.name for f in _skill_dirs())


def _all_kernel_skills() -> tuple[KernelSkill, ...]:
    """Strictly load + validate the whole shipped set. Exercised by a unit test so
    a malformed kernel folder fails CI before it can reach a freeze."""
    return tuple(_load_skill(f) for f in _skill_dirs())


def kernel_skills_for(slug: str) -> list[KernelSkill]:
    """The kernel skills an agent receives: every `*`-mapped skill (the baseline)
    plus those naming this slug. Only folders that target this slug are fully
    validated, so a malformed folder for one agent can't 500 the freeze of an
    unrelated agent (the strict `_all_kernel_skills()` CI check guards the shipped
    set). Empty for an agent no kernel skill targets."""
    out: list[KernelSkill] = []
    for folder in _skill_dirs():
        agents = _agents_of(folder)
        if agents is None:
            continue
        if _WILDCARD in agents or slug in agents:
            out.append(_load_skill(folder))
    return out
