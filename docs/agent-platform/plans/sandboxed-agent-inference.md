# Design — sandboxed agent inference for advanced capabilities

**Status:** draft / open questions. **Owner:** ben.

This is `_TODO.md` item #1. The motivating use case is "an agent that
writes and runs PostHog code on our infrastructure" — an agent that
can read the repo, propose edits, run tests, and ship a patch. What
we'd need: a higher-trust sandbox profile, code-execution tooling,
repo access semantics, output / artifact channel, and composition with
the existing approval + elevation + secrets layers.

## 1. Problem

Today's sandbox story is well-suited for **author-frozen** custom
tools but not for **agent-authored** code:

- **Custom tools** (`spec.tools[].kind === 'custom'`,
  `services/agent-shared/src/sandbox/sandbox.ts`): TypeScript written
  by the agent author, compiled at bundle time, loaded into a
  `vm.createContext()` (or Docker, or Modal — three implementations
  with the same interface). Resources: 30s wall, 512MB, no filesystem,
  egress through a proxy with a host allowlist, secrets delivered as
  nonces. Tight.
- **Hog VM** (`common/hogvm/`): a bytecode interpreter used for CDP /
  HogQL. 64MB memory, 5s timeout, no filesystem, no network. Tighter
  still. Today's Cyclotron job executor uses this.
- **Repo access**: zero. No native tool reads PostHog source. The
  custom-tool sandbox blocks `require('fs')`.

What we _don't_ have:

- A "the agent can write Python at runtime" tier — a sandbox where the
  agent's tool call _is_ "execute this code".
- Mounted-repo semantics — a working copy where the agent can read /
  diff / patch files.
- An artifact channel — output beyond a JSON tool result. Today every
  tool result must fit in `ConversationMessage` content.
- A trust-profile concept — the existing sandbox is "one tier, locked
  down". There's no "this agent is allowed to do more".

Concrete examples that this plan unlocks:

- An "internal codebase Q&A" agent that grep / reads / summarizes
  PostHog source for an engineer.
- A "refactor proposer" agent that reads a directory, drafts a patch,
  runs the relevant test file, and emits a diff for human review.
- A "release health investigator" that runs a HogQL query, finds an
  anomaly, then writes a Python script to reproduce it locally
  against the read replica.

Non-goal (for this plan): a fully-automated "merge agent". Anything
that mutates `main` or pushes to remotes goes through human approval
(see [approval-gated-tools.md](approval-gated-tools.md)).

## 2. What "high-trust sandbox" precisely means

Introduce an explicit **trust profile** on the spec. Each profile
maps to a sandbox implementation + a capability matrix. Today's
custom-tool sandbox becomes the lowest tier; new tiers stack capability:

| Profile         | Runtime                         | Network                  | Filesystem                                     | Code exec                | Wall time     | Mem   |
| --------------- | ------------------------------- | ------------------------ | ---------------------------------------------- | ------------------------ | ------------- | ----- |
| `none`          | n/a (native tools only)         | n/a                      | n/a                                            | none                     | n/a           | n/a   |
| `frozen`        | InProcess `vm.Context` / Docker | proxy allowlist          | none                                           | author-frozen JS only    | 30s/turn      | 512MB |
| `repo-readonly` | Modal container (ephemeral)     | proxy allowlist          | mounted PostHog repo (read-only)               | python + bash            | 10min/session | 4GB   |
| `repo-write`    | Modal container (ephemeral)     | proxy allowlist          | mounted PostHog repo (read + write, ephemeral) | python + bash + git      | 30min/session | 8GB   |
| `repo-pr`       | Modal container (ephemeral)     | proxy allowlist + GitHub | mounted PostHog repo + git creds (scoped)      | python + bash + git + gh | 60min/session | 8GB   |

- `frozen` is today's behavior. Existing agents stay here by default.
- `repo-readonly` is the cheapest unlock — Q&A over the codebase, no
  write risk.
- `repo-write` is "edit and run tests"; writes are ephemeral (lost
  when the container dies). No remote access. A new `@posthog/diff`
  tool emits the working tree's diff as an artifact (see §7).
- `repo-pr` is the only tier with persistent effect: it can `git
push` to a branch (never `main`) and call `gh pr create`. Every
  `git push` and every `gh` call is approval-gated.

Critically, **the model cannot escape its tier**. The runner refuses
to dispatch a `repo-write` tool from an agent declared as `repo-readonly`.
The sandbox refuses to execute privileged operations even if the model
crafts the call. Defense in depth: tier check at spec freeze, at
dispatch, and at sandbox primitive.

## 3. Spec config — declaring a trust profile

Extend `AgentSpec` in `services/agent-shared/src/spec/spec.ts`:

```typescript
export const TrustProfileSchema = z.enum(['none', 'frozen', 'repo-readonly', 'repo-write', 'repo-pr'])

export const SandboxConfigSchema = z.object({
  trust_profile: TrustProfileSchema.default('frozen'),

  // Mount points — only meaningful for repo-* profiles.
  // Defaults: PostHog monorepo at /workspace.
  workspace: z
    .object({
      repo: z.string().default('posthog/posthog'),
      ref: z.string().default('main'), // branch / tag / sha; freeze-time pinned
      paths: z.array(z.string()).default(['.']), // subset to mount; default whole repo
      exclude: z.array(z.string()).default([]), // gitignore-style; supplemental
    })
    .optional(),

  // Inner runtime tunables. Per-profile defaults apply (§2 table).
  limits: z
    .object({
      max_session_seconds: z.number().int().positive().optional(),
      max_session_mb: z.number().int().positive().optional(),
      max_artifact_bytes: z
        .number()
        .int()
        .positive()
        .default(10 * 1024 * 1024),
    })
    .optional(),
})
```

Spec validation at freeze time:

- `trust_profile: 'repo-write'` or higher requires the spec author to
  be on a **platform-side allowlist** (`AgentApplicationTrustGrant`
  Django table). This is _not_ self-service. Promoting an agent to a
  higher tier is an explicit admin action with an audit row.
- `workspace.ref` must resolve to a real ref at freeze time and is
  pinned by SHA in the frozen spec. Drift is impossible mid-session.
- `repo-pr` additionally requires a per-agent GitHub App
  installation (scoped to the agent's branch namespace, e.g.
  `agents/<agent_slug>/*`). Configured via the secrets / integrations
  layer.

## 4. Sandbox runtimes — building on the Modal stub

The existing `sandbox-modal.ts` is a deferred stub for production
isolated sandboxes. This plan promotes it from stub to first-class for
`repo-*` profiles.

### 4.1 Modal-backed sandbox

Each `repo-*` session gets:

- A fresh Modal sandbox (long-lived during the session, billed by
  wall-time). Modal's per-sandbox isolation + serverless model fits
  the "ephemeral, per-session" requirement.
- The repo cloned + checked out at the spec's pinned ref. Cached as a
  Modal Volume for fast startup (~few seconds on warm cache).
- Python + Node + standard build tooling preinstalled. The base image
  matches PostHog's CI base (so tests that pass in CI can pass here).
- Hog runtime preinstalled — the agent can call `hog run` if it
  wants.
- Egress proxy bound to the sandbox's outbound: every HTTP call goes
  through the same allowlist + nonce-substitution gate the custom-tool
  sandbox uses today (`services/agent-shared/src/sandbox/sandbox.ts`).

This stays inside the existing `SandboxImpl` interface
(`sandbox.ts:1-50`). The runner is sandbox-agnostic — `dispatch-one.ts`
already calls `sandbox.invoke({ toolId, args })` without caring
whether it's InProcess, Docker, or Modal. New profile selection is a
factory at session start.

### 4.2 Fallback / dev-mode story

Local dev needs to run repo-tier agents without Modal credentials. The
existing Docker sandbox stub gets fleshed out to mount a local clone
read-only / read-write as the same `workspace`. Same `SandboxImpl`
interface; differences are invisible to the agent author.

### 4.3 What stays Hog-only

Custom tools authored against the existing Hog VM continue to run
through `frozen` profile sandboxes. Hog is for fast, frozen, untrusted
work; the new tiers are for agent-authored Python / bash.

## 5. Code-execution tool family

New native tools, available only when `trust_profile != 'frozen'`:

```typescript
// trust_profile >= 'repo-readonly'
@posthog/sandbox-read-file(path: string) → { content, sha }
@posthog/sandbox-grep(pattern, paths?, max_results?) → { matches }
@posthog/sandbox-list-dir(path, max_depth?) → { entries }
@posthog/sandbox-exec(cmd: string, args: string[], stdin?, timeout_s?) → { stdout, stderr, exit_code }
// exec is whitelisted: ls, cat, head, tail, grep, find, python, node, hog, pytest, jest...
// Network commands (curl, wget, ssh) blocked at the wrapper level.

// trust_profile >= 'repo-write'
@posthog/sandbox-write-file(path: string, content: string) → { sha, replaced }
@posthog/sandbox-apply-patch(diff: string) → { applied_files, failed_hunks }
@posthog/sandbox-diff(paths?) → artifact-ref  // returns artifact handle, not inline content
@posthog/sandbox-run-tests(suite: string) → { stdout, stderr, exit_code, junit_xml? }

// trust_profile == 'repo-pr'
@posthog/sandbox-git-push(branch: string, message: string) → { commit_sha }   // approval-gated
@posthog/sandbox-gh-pr-create(title, body, base) → { pr_url, pr_number }      // approval-gated
@posthog/sandbox-gh-pr-comment(pr_number, body) → { comment_id }              // approval-gated
```

Two design choices worth flagging:

- **`exec` is a whitelisted shell**, not a free `/bin/sh`. The
  whitelist is per-profile. Adding entries requires a platform-side
  change, not spec authorship.
- **No raw `subprocess`-equivalent in `repo-readonly`**. The model can
  invoke Python only via `exec("python", ["-c", "..."])` with the
  same whitelist machinery. Python inside the sandbox itself still
  has full stdlib (it's a separate process namespace); the whitelist
  governs what the agent _initiates_, not what the agent's
  subprocesses do internally.

The approval-gating column in the `repo-pr` tools means: the spec's
`approvers` policy from [approval-gated-tools.md](approval-gated-tools.md)
applies. Every push, every PR, every PR comment goes through the same
human-in-the-loop machinery. No automatic merges.

## 6. Repo access semantics

What does the model see when it `read_file("posthog/api/agent_application.py")`?

- The mounted repo at the spec's pinned ref. For `repo-readonly` and
  `repo-write` agents, this is _always_ the pinned ref — the agent
  cannot accidentally operate on `main` mid-week.
- For `repo-pr` agents, the working tree starts at the pinned ref but
  the agent can `git checkout -b <branch>` to a new ephemeral branch.
  Pushes go _only_ to `agents/<agent_slug>/*` (enforced by the GitHub
  App scope).
- Symlinks are flattened at clone time. The sandbox cannot escape via
  `..` paths.
- The `.git` directory is read-only for `repo-readonly`, writable for
  `repo-write`+ (so `git status`, `git diff`, `git add` work).

Exclusions baked into the platform:

- `.env*`, `secrets/*`, anything matched by a platform-side
  `~/.agentignore` are never mounted.
- The PostHog cookbook of "files agents should never touch"
  (e.g. `posthog/personhog_client/proto/generated/*`) is mounted
  read-only even in `repo-write`. Editing those is a spec-level
  capability that doesn't exist.

## 7. Output / artifact channel

A tool result today is a JSON message that has to fit in conversation
context. Big artifacts (diffs, test logs, generated files) don't fit.
Introduce an **artifact channel**:

```typescript
// SandboxImpl exposes:
sandbox.writeArtifact(sessionId, name, bytes, mimeType): { artifact_id, url }
sandbox.readArtifact(artifact_id): bytes
```

Storage: artifacts land in object storage (S3 / GCS) under a per-session
prefix. Lifecycle = session lifecycle (deleted when session terminates,
unless persistent flag set). Bound by
`spec.sandbox.limits.max_artifact_bytes` (default 10MB).

Tool results that exceed an inline threshold (~16KB) emit an
**artifact handle** instead:

```jsonc
// returned to the model
{
  "kind": "artifact",
  "artifact_id": "art_abc123",
  "name": "diff.patch",
  "size_bytes": 184320,
  "preview": "diff --git a/posthog/api/foo.py b/posthog/api/foo.py\n...\n[truncated; full content at artifact:art_abc123]",
}
```

The model can:

- Reference the artifact ID in subsequent tool calls (e.g.
  `apply_patch(artifact_ref="art_abc123")` to re-apply its own diff).
- Ask the user to review it — the PostHog UI deep-links to a viewer
  for known mime types (diffs, JUnit XML, plain text).

On approval flows (e.g. PR creation), the approval surface from
[approval-gated-tools.md](approval-gated-tools.md) §7 displays the
linked artifacts inline so the human can see the diff before
approving.

## 8. Composition with approvals, elevation, secrets

**Approvals** — every `repo-pr` tool (push, PR create, PR comment)
defaults to `requires_approval: true`. Spec validation enforces this
at freeze time; you cannot publish a `repo-pr` agent without an
approval policy. `repo-write` tools are optional approval-gated; the
author decides. `repo-readonly` tools default to no gate.

**Elevation** — high-trust agents almost always have
`spec.auth.mode != 'public'`. Spec validation hard-rejects
`trust_profile != 'frozen'` combined with `auth.mode == 'public'`.
Session ACLs from
[per-session-access-elevation.md](per-session-access-elevation.md)
work as today — but for `repo-pr` agents the platform additionally
requires the session's primary principal to hold the `agent_writer`
PostHog role.

**Secrets** — the existing nonce-substitution boundary (egress
proxy) extends to the Modal sandbox. The agent's code never sees
plaintext API keys; substitution happens in the proxy. The new
sandbox primitives can _read_ secret names but not values
(`sandbox.secrets.list()` returns names; there's no `value()` outside
the proxy boundary). Same shape as
`services/agent-shared/src/sandbox/sandbox.ts:27` today.

## 9. Audit + observability

Every code-execution tool call emits a structured log entry that
joins the existing session log_entries (ClickHouse). Specifically:

- `exec` calls log `{cmd, argv, exit_code, stdout_bytes, stderr_bytes,
duration_ms}` (not stdout content — that's in the artifact).
- `write_file` / `apply_patch` log path + size + sha of new content.
- `git push` / `gh pr create` log branch, commit SHA, PR URL.
- All `repo-*` tool calls additionally write to the
  `agent_session_acl_audit` table (per
  [per-session-access-elevation.md](per-session-access-elevation.md)
  §3) under `action: "code_exec"` so administrators can trace what
  high-trust agents did across sessions.

Live observability: a Grafana panel surfaces `code_exec_total{tool,
trust_profile, agent_slug}`, `artifact_bytes_written_total`,
`gh_push_total{agent_slug, base_branch}`.

## 10. Open questions

1. **Hog VM vs full container.** A "weight-loss" version of this plan
   would use Hog for everything — agent writes Hog at runtime, runs
   in the existing 64MB / 5s sandbox. Cheaper, slower iteration, no
   filesystem. Worth exploring as a parallel `hog-write` profile
   that's strictly weaker than `repo-readonly`. Punt to a follow-up
   unless we hit Modal cost ceilings early.
2. **State leakage between sessions.** Modal volume caching speeds
   repo clones but risks bleed-through (a previous session's stash
   shows up in the next). Resolution: every session starts with a
   fresh `git reset --hard <pinned_sha> && git clean -fdx`. Document
   and test.
3. **Cost ceiling.** A long-running `repo-pr` agent at 60min wall
   time / 8GB / Modal pricing could be expensive per session. Need a
   per-team cost cap (separate from the rate-limit cap in
   [rate-limiting-sessions.md](rate-limiting-sessions.md)) measured
   in dollars-per-day. v2.
4. **Self-modification.** Should a `repo-pr` agent be able to edit
   _its own agent definition_? Strictly no for v0 — the spec freeze
   model assumes immutable specs per revision. A separate plan
   covers "an agent that proposes spec edits"
   (see `agent-authoring-flow.md` and the self-healing plan).
5. **Test runner integration.** `sandbox-run-tests` invokes pytest /
   jest from the agent's perspective, but PostHog's test commands are
   `hogli test` which wraps everything. Two options: (a) make
   `sandbox-run-tests` shell out to `hogli test`; (b) preinstall
   hogli in the Modal image. Going with (b) — match CI.
6. **Multi-repo.** The current design assumes one repo
   (`posthog/posthog`). A future need: agents that operate across
   `posthog/posthog-js`, `posthog/posthog-foss`, etc. Modeled as
   multiple `workspace[]` mounts. Punt.
7. **GitHub App vs PAT.** `repo-pr` agents push and PR. Using a
   GitHub App (scoped install per agent) is more secure than a PAT.
   But the App setup is per-organization-installation, which adds
   friction. For v0 internal use: PAT scoped to
   `agents/<agent_slug>/*` branch namespace. v1: full GitHub App.
8. **Web search / web fetch in higher tiers.** The existing
   `@posthog/web-fetch` tool runs in the InProcess sandbox.
   `repo-readonly`+ agents probably want curl-style access too.
   Same egress proxy + allowlist applies. Native tool from the
   existing set, available across all profiles.
9. **Per-session log volume.** A `repo-write` session running pytest
   on the whole repo can produce hundreds of MB of output, all of
   which lands as artifacts. Per-session artifact byte ceiling
   (current default 10MB) is too low. Bump default to 100MB for
   `repo-*` profiles; spec can override.
10. **Approval payload preview UX.** The approval surface from
    [approval-gated-tools.md](approval-gated-tools.md) shows
    `proposed_args`. For `apply_patch` the args _are_ the diff — but
    diffs can be huge. UI should render the diff with syntax
    highlighting, fold-by-default for hunks past N lines.

## 11. Rollout

**v0** (internal-only, repo-readonly):

- Promote `sandbox-modal.ts` from stub. Wire Modal credentials.
- Add `trust_profile` + `workspace` + `limits` to
  `SandboxConfigSchema`. Validate at freeze.
- Implement `read_file`, `grep`, `list_dir`, `exec` (whitelisted) for
  `repo-readonly`.
- Implement artifact channel (writeArtifact / readArtifact) + S3 store.
- Build one canonical agent: "PostHog codebase Q&A" — given a query,
  reads relevant files, summarizes. Internal-only, dogfood at
  PostHog. Validates the pipeline end-to-end.

**v1** (repo-write internally):

- Add `write_file`, `apply_patch`, `diff`, `run_tests` for
  `repo-write`.
- Build the "refactor proposer" agent — reads a spec, drafts a
  diff, runs tests, emits the diff to a reviewer.
- Approval-gating wired for `apply_patch` by spec default.
- Cost dashboards (open q #3).

**v2** (repo-pr, broader rollout):

- GitHub App setup. Branch namespace scoping.
- `git_push`, `gh_pr_create`, `gh_pr_comment` with mandatory
  approval gates.
- Document the trust-tier promotion process for non-PostHog teams.
- Audit dashboards mature.

**v3** (cross-org GA):

- Full self-service spec authoring for trust profiles up to
  `repo-readonly`. Higher tiers stay platform-admin-gated.

## 12. Dependencies + what this enables

**Depends on:**

- [approval-gated-tools.md](approval-gated-tools.md) — `repo-pr`
  tools are unusable without per-tool approval gating.
- [per-session-access-elevation.md](per-session-access-elevation.md)
  — high-trust agents need strict principal enforcement; reuses the
  ACL + audit infrastructure.
- [rate-limiting-sessions.md](rate-limiting-sessions.md) — Modal
  sandboxes are expensive; per-team cost caps build on the
  rate-limit infrastructure.

**Enables / interacts with:**

- A future "self-healing agents" plan (`_TODO.md` #2) — the
  introspection loop where an agent rewrites its own definition needs
  this sandbox to test the rewrite.
- `agent-authoring-flow.md` — the authoring AI itself can graduate to
  `repo-readonly` so it can inspect the platform's own source while
  drafting specs.
- A future "executable runbooks" plan — incident response agents
  that need to read configs + run diagnostic scripts use this
  exact substrate.
- A future "automated PR reviewer" agent — reads diff, runs targeted
  tests, suggests changes. Lives at `repo-readonly` + comment-only
  `repo-pr`.
