# Skills Tab v2 — Implementation Plan

Owner: Peter Kirkham
Status: Ready to build
Last updated: 2026-06-11

## Summary

The Skills tab today is a read-only list: `SkillsService.listSkills()` scans four
sources (bundled, user, repo, marketplace plugins), one tRPC query feeds
`SkillsView`, and the detail panel renders only `SKILL.md`. There is no create,
edit, delete, live refresh, marketplace browsing, cloud sync, or visibility into
the rest of a skill directory (`references/`, `scripts/`).

This plan turns the tab into a full skill manager across seven stacked PRs:
full multi-file rendering, CRUD for user/repo skills, live refresh, validation,
skills.sh marketplace browse + install, PostHog cloud team skills via the
existing `LLMSkill` API, and Codex skills unification.

## Goals

- Create, edit, and delete user (`~/.claude/skills`) and repo
  (`{repo}/.claude/skills`) skills entirely in-app.
- Render skills as what they are: directories (`SKILL.md` + `references/` +
  `scripts/` + assets), not a single markdown file.
- Browse and install community skills from skills.sh without leaving the app.
- Publish skills to the team and consume team skills via the existing PostHog
  cloud `LLMSkill` API.
- Unify with Codex: read the user's Codex skills, import them, and mirror
  user skills out so they work in any agent. Bring your skills, use them
  anywhere.

## Non-goals (explicitly out of scope)

- **No changes to the official PostHog skills pipeline.** The
  `agent-skills-latest` release, `skills.zip`, the context-mill omnibus zips,
  `update-skills-saga.ts`, and the 30-minute refresh stay exactly as they are.
  No manifest, no versioning added to that channel.
- **No editing of bundled or plugin-marketplace skills.** Read-only, enforced
  server-side, forever.
- **No upstream version tracking for installed skills.** Install is a copy.
  Once installed, a skill is a local user skill; we forget where it came from
  except for an "Installed" badge in the marketplace. No hashes, no diffs, no
  update notifications. Reinstall (confirm + overwrite) is the update story.
- No new npm dependencies and no bundle-size impact. Marketplace browsing is
  runtime HTTP; install uses the existing `fflate`-based `extract-zip.ts`.

## Design principles

1. **A skill is a directory, not a file.** `SKILL.md` is the manifest; the
   directory is the unit of install, edit, share, and render.
2. **Editability follows directory ownership.** Directories we own on the
   user's behalf (`~/.claude/skills`, `{repo}/.claude/skills`) are writable.
   Directories owned by other systems (runtime plugin dir, plugin-manager
   install paths, the Codex dir for skills we didn't put there) are read-only.
3. **Install = copy, then it's yours.** No tethering to upstream.
4. **Write-path guards live in workspace-server**, not the UI. Every mutation
   validates the target resolves under a writable skills root.
5. **Standard layering** (per `AGENTS.md`): fs/zip/watchers/HTTP-download in
   `workspace-server` behind one-line tRPC forwards; PostHog cloud API calls in
   a `core` service via injected `api-client`; pure decisions (validation,
   shadowing, list merging) in `core`; UI renders and calls one hook per
   query/mutation.

## Key findings (already verified)

### PostHog cloud already has the skills model and API

No new Django models needed. In `PostHog/posthog`:

- `LLMSkill` (`products/ai_observability/backend/models/skills.py`): `name`,
  `description`, `body` (the SKILL.md markdown), `allowed_tools`, `metadata`,
  versioned via `version` + `is_latest`, soft-delete, unique on
  `(team, name, version)`.
- `LLMSkillFile`: companion files (`path`, `content`) — multi-file skill
  directories are supported.
- `LLMSkillViewSet` at `/api/projects/:id/llm_skills/` (and
  `/api/environments/:id/...`): CRUD, name-addressed routes, `resolve`,
  `archive`, `duplicate`, file get/delete. API scopes `llm_skill:read|write`.
- Currently **team-scoped only** and behind the `LLM_ANALYTICS_SKILLS` beta
  flag. The only posthog-side work in this plan is flag/scope rollout
  (see PR 6a).

### Codex skills dir

`update-skills-saga.ts` already syncs bundled skills to `~/.agents/skills`
(`CODEX_SKILLS_DIR`). PR 7 reads that directory back and mirrors user skills
into it.

### Reusable seams in this repo

| Need | Existing seam |
| --- | --- |
| Zip extraction | `packages/workspace-server/src/services/posthog-plugin/extract-zip.ts` (`fflate`) |
| File writes | `packages/workspace-server/src/services/fs/service.ts` (`writeRepoFile` pattern) |
| File watching | `packages/workspace-server/src/services/watcher/service.ts` (`@parcel/watcher`, debounced) |
| tRPC subscription pattern | `packages/host-router/src/routers/workspace.router.ts` (async-generator `subscription`) |
| Mutation pattern | `packages/host-router/src/routers/fs.router.ts` |
| Editor | `packages/ui/src/features/code-editor/` (CodeMirror, `useCodeMirror`) |
| Versioned JSON state file | `~/.claude/plugins/installed_plugins.json` reader in `skill-discovery.ts` |
| API resource client pattern | MCP installation methods in `packages/api-client/src/posthog-client.ts` (~L2671–2798) |

## Skill sources after this plan

| Source | Path | Listed | Editable | Notes |
| --- | --- | --- | --- | --- |
| `bundled` | runtime plugin dir | yes | **no** | Untouched official pipeline |
| `user` | `~/.claude/skills` | yes | yes | Includes marketplace installs |
| `repo` | `{repo}/.claude/skills` | yes | yes | Per workspace folder |
| `marketplace` | plugin install paths | yes | **no** | Claude plugin manager owns these |
| `codex` (new) | `~/.agents/skills` | yes | **no** (import to edit) | Deduped against bundled + mirrored names |
| `team` (new) | PostHog cloud `LLMSkill` | yes | via publish | Install materializes a local copy |

---

## The PR stack (Graphite)

Build this as a Graphite stack so review can proceed top-down while later PRs
are in flight. Suggested layout:

```
main
└── skills-01-full-rendering        # PR 1
    └── skills-02-crud              # PR 2
        └── skills-03-live-refresh  # PR 3
            └── skills-04-validation        # PR 4
                └── skills-05-marketplace   # PR 5
                    └── skills-07-codex     # PR 7
└── skills-06a-team-read            # PR 6a (independent stack off main; rebase onto 01 if it lands first)
    └── skills-06b-team-publish     # PR 6b
```

Workflow:

```bash
gt create skills-01-full-rendering -m "feat(skills): render full skill directories"
# ...work, commit...
gt create skills-02-crud -m "feat(skills): create/edit/delete user and repo skills"
# ...
gt submit --stack          # open/refresh PRs for the whole stack
gt sync && gt restack      # after a PR lands or main moves
```

Notes:
- PRs 1→5→7 are a true dependency chain (each builds on the previous one's
  schemas/components). Keep them in one stack.
- PR 6a/6b only touch `api-client`, `core`, and a UI group; they can be a
  second stack worked in parallel and restacked when convenient.
- Each PR must pass `pnpm typecheck`, `pnpm lint`, `pnpm test`, and
  `node scripts/check-host-boundaries.mjs` independently — every PR is
  shippable on its own.

---

### PR 1 — Render full skill directories (read-only foundation)

Everything later builds on this. Skills become directories in the UI.

**Backend**
- `SkillsService.getSkillContents(skillPath)` → file tree (relative paths,
  sizes) + `readSkillFile(skillPath, relPath)`. Both validate the path resolves
  inside a directory returned by skill discovery — this must not become an
  arbitrary-filesystem-read endpoint.
- `host-router` `skills.contents` / `skills.readFile` queries (one-line
  forwards). Zod output schemas in `workspace-server/src/services/skills/schemas.ts`.

**Shared**
- Add derived `editable: boolean` to `SkillInfo` (`user`/`repo` → true,
  `bundled`/`marketplace` → false). Computed in `SkillsService`, not the UI.

**UI**
- `SkillDetailPanel`: file list/tree for the skill directory. `SKILL.md`
  renders as today (frontmatter stripped, markdown); other files open in
  read-only CodeMirror via `useCodeMirror`. Lock badge on non-editable skills.

**Acceptance**
- A bundled skill with `references/` and `scripts/` shows every file and its
  contents, read-only.
- Path traversal attempts (`../`) on the new endpoints are rejected (unit
  tested).

---

### PR 2 — Create / edit / delete for user and repo skills

**Backend**
- `SkillsService` mutations: `createSkill({scope, repoPath?, name})` (scaffolds
  directory + templated `SKILL.md`), `saveSkillFile`, `deleteSkillFile`,
  `deleteSkill`, `renameSkill`.
- Hard guard on every mutation: resolved target must be under
  `~/.claude/skills` or a workspace folder's `.claude/skills`. Anything else
  (bundled, plugin install paths, runtime plugin dir, Codex dir) is rejected
  server-side. Unit-test the guard directly.
- `host-router` mutations, one-line forwards.

**UI**
- "New skill" button → scope picker (Your skills / This repository) → scaffold
  and open in edit mode.
- Edit mode in the detail panel: small form for frontmatter `name` /
  `description` (users never hand-edit YAML), CodeMirror for the body, add /
  rename / delete files under the skill directory.
- Delete skill with confirmation. Non-editable sources show no edit affordances.

**Acceptance**
- Round-trip: create → edit body + frontmatter → file on disk is correct →
  delete. Frontmatter writer output re-parses with `parse-skill-frontmatter.ts`.
- Mutations against a bundled skill path fail with a clear error.

---

### PR 3 — Live refresh

**Backend**
- Watch `~/.claude/skills` and each workspace folder's `.claude/skills` using
  `WatcherService`. Expose `skills.watch` tRPC subscription (async-generator
  pattern from `workspace.router.ts`), emitting a debounced "skills changed"
  event.

**UI**
- Subscribe once (contribution or hook at the SkillsView boundary) and
  invalidate the `skills.list` / `skills.contents` queries on events. Drop the
  30s stale-time reliance.

**Acceptance**
- `touch ~/.claude/skills/foo/SKILL.md` from a terminal updates the open tab
  within ~1s. Edits made by an agent session appear without manual refresh.

---

### PR 4 — Validation + shadowing signals

**Core (pure decisions, no I/O)**
- `analyzeSkills(skills: SkillInfo[])` in `@posthog/core`: missing/empty
  description, frontmatter-name vs directory-name mismatch, oversized
  `SKILL.md` (context-cost warning), and name collisions across sources with
  explicit "which one wins" resolution.

**UI**
- Health badge on `SkillCard`; callouts in the detail panel (e.g. "shadowed by
  your user skill of the same name").

**Acceptance**
- Unit tests on `analyzeSkills` cover each rule and the shadowing precedence.

---

### PR 5 — skills.sh marketplace: browse + install

Install is **copy-and-forget**: download, extract into `~/.claude/skills/<name>`,
done. From that moment it is an ordinary, editable user skill. No upstream
tracking, no hashes, no diffs, no update checks.

**Backend (`workspace-server`)**
- New `SkillsMarketplaceService`:
  - `search(query)` → queries the skills.sh index at runtime (fallback: GitHub
    repo search for `SKILL.md` directories). Nothing cached to disk.
  - `preview(ref)` → fetches the skill's full file list + contents for
    pre-install rendering (reuses PR 1's tree/file UI).
  - `install(ref)` → downloads the repo tarball (GitHub codeload), extracts the
    skill directory with `extract-zip.ts`, copies into `~/.claude/skills/<name>`.
  - `installed.json` in `~/.claude/skills/` (versioned-JSON pattern from
    `installed_plugins.json`): `{ version, installed: { [name]: { repo } } }`.
    Its **only** purpose is the "Installed" badge in browse results.
- Name collision or reinstall → caller must pass `overwrite: true` (UI confirms
  "this will replace your local version").
- `host-router` `skills.marketplace.*` routes, one-line forwards.

**UI**
- "Browse" tab inside SkillsView: search, results with install counts /
  publisher, full file-tree preview **before** install (PR 1 components),
  explicit warning chip when a skill contains `scripts/` (installed skills can
  execute code — never install sight-unseen).
- Install / Reinstall buttons with the overwrite confirm. Installed skills
  appear under "Your skills" like any other user skill.

**Acceptance**
- Search → preview (all files visible) → install → skill is listed under "Your
  skills", editable; browse shows "Installed"; reinstall after a local edit
  prompts and then overwrites.
- No new package.json dependencies; bundle size unchanged.

Split into 5a (backend) / 5b (UI) if review size demands.

---

### PR 6a — PostHog cloud team skills: read path

**posthog/posthog (separate small PR, the only non-Code work in this plan)**
- Roll out / gate `LLM_ANALYTICS_SKILLS` for PostHog usage and confirm the
  desktop OAuth token carries `llm_skill:read` and `llm_skill:write` scopes.
  No model or endpoint changes.

**api-client**
- `llm_skills` methods following the MCP-installation pattern
  (`posthog-client.ts` ~L2671): `listLlmSkills()`, `getLlmSkillByName(name)`,
  `resolveLlmSkill(name)`, `listLlmSkillFiles(id)`. Zod schemas alongside.

**core**
- New `TeamSkillsService` (`@posthog/core`, api-client injected per the
  placement rules) exposing list/read, plus the merged local+team listing
  decision so the UI keeps one hook.

**UI**
- "Team" group in SkillsView (new `team` source), read-only detail view
  rendering `body` + `LLMSkillFile`s through the PR 1 components.

**Acceptance**
- With the flag on, team skills list and render; with it off, the group is
  absent and nothing errors.

---

### PR 6b — Team skills: publish + install locally

**Publish**
- "Publish to team" on any user/repo skill: workspace-server reads the
  directory; `TeamSkillsService` creates a new `LLMSkill` version (+
  `LLMSkillFile` rows). Versioning comes free from the model's
  `version`/`is_latest`. Re-publishing bumps the version.

**Install locally**
- "Install" on a team skill materializes it into `~/.claude/skills` (agents
  need files on disk), then it follows the same copy-and-forget rule as
  marketplace installs: it's a local user skill, reinstall-to-update via the
  Team group with a confirm-overwrite.

**Acceptance**
- Publish a multi-file skill → teammate sees it in the Team group → installs →
  identical directory on their disk → original author edits + republishes →
  teammate reinstalls and gets the new version.

---

### PR 7 — Codex unification ("bring your skills, use them anywhere")

**Read: Codex → tab**
- Add `~/.agents/skills` as a discovery source in `SkillsService`; new `codex`
  value in `SkillSource`. Same `findSkillDirs` call, one more root.
- Dedupe by name: skip anything matching a bundled skill (our saga put those
  copies there) or a mirrored user skill (below). What remains is genuinely the
  user's Codex-only skills.
- UI: "Codex" group with an **Import** action — copies the directory into
  `~/.claude/skills`, after which it's an ordinary editable user skill.

**Write: your skills → Codex**
- Extend the existing bundled→Codex sync to also mirror `~/.claude/skills`
  into `~/.agents/skills` (one-way, ours out). Skills created, edited, or
  installed in PostHog become available to Codex sessions automatically.
- Safety rule: never overwrite a skill in `~/.agents/skills` we didn't put
  there. Track mirrored names (small state file next to the existing sync), and
  on collision skip + surface the conflict in the tab.

**Acceptance**
- A skill authored in Codex (`~/.agents/skills/foo`) appears in the Codex
  group; Import makes it editable under "Your skills"; the mirror then carries
  the imported copy back without clobbering or duplicating.
- A user skill created in the tab appears in `~/.agents/skills` after the next
  sync.

---

## Security notes

- Skills can contain `scripts/` that agents execute, and `SKILL.md` content is
  injected into agent context. **A marketplace install is code execution, not a
  content download.** Hence: full file preview before install (PR 5), the
  `scripts/` warning chip, and no silent/automatic installs or updates anywhere
  in this plan.
- All write endpoints validate the resolved path against the writable roots in
  workspace-server (PR 2). The read endpoints from PR 1 validate against
  discovered skill directories. Both get direct unit tests including `../`
  traversal.
- Team skills inherit PostHog access control (`AccessControlPermission`, API
  scopes) — nothing custom on our side.

## Testing

- Unit (Vitest, colocated): frontmatter round-trip, path guards, `analyzeSkills`
  rules, lockfile/`installed.json` read-write, dedupe + mirror rules, api-client
  schema parsing. Fake injected dependencies per `docs/testing.md`.
- E2E (Playwright, `tests/e2e/`): one flow per PR — render a multi-file skill;
  create/edit/delete; live-refresh on external edit; marketplace
  search→preview→install; team publish→install; codex import.
- After `@posthog/shared` / `@posthog/platform` changes, rebuild/typecheck
  dist; after `core` changes, `biome lint packages/core` with zero
  `noRestrictedImports`.

## Rollout order

| Phase | PRs | Outcome |
| --- | --- | --- |
| 1 | 1, 2, 3 | The tab is a real skill manager (view all files, CRUD, live) |
| 2 | 4, 5 | Quality signals + community marketplace |
| 3 | 6a, 6b, 7 | Team sharing + Codex unification |

PRs 1–4 carry no external dependencies and can start immediately. PR 5 depends
only on skills.sh's public index. PR 6 needs the posthog flag/scopes PR
(file it when 6a starts). PR 7 has no external dependencies.
