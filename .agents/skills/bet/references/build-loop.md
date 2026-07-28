# `run_config.build_loop` — a real coding agent, gated by the gauntlet

Extends [managed-run-config.md](managed-run-config.md). A plain managed bet's
`run_config.command` runs whatever script the user wants (still true). A
`build_loop`-configured bet instead runs a _real headless coding agent_
(Claude Code, reference implementation) through a fixed two-role choreography
that Foundry itself orchestrates: an optional test-writer, then a builder
that retries against the gauntlet's feedback until it passes or exhausts its
attempt budget. Nothing here changes execution_mode, event kinds, or the
gauntlet (ADR 4) — `build_loop` only decides what `foundry-run-bet` starts in
its place: `foundry-build-bet`.

```json
{
  "build_loop": {
    "target_repo": { "url": "https://user:token@gitea.internal/org/repo.git", "base_ref": "main" },
    "test_writer": { "command": "claude -p \"$(cat <<'EOF'\n...\nEOF\n)\" --dangerously-skip-permissions" },
    "builder": {
      "command": "claude -p \"$(cat <<'EOF'\n...\nEOF\n)\" --dangerously-skip-permissions",
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    },
    "max_gate_iterations": 3
  }
}
```

- `target_repo.url` — the tokened https clone URL (same convention as
  `memory_repo_url`: credentials embedded, never typed in conversation).
  Needs read to clone and write to push.
- `target_repo.base_ref` — the ref the test-writer (or the builder, if
  there's no test-writer) starts from.
- `test_writer` — optional. Omit it entirely for a bet that doesn't need
  builder/test separation (e.g. acceptance tests already exist in the target
  repo, or the bet is low-stakes enough that `gate_config.protected_paths`
  isn't worth the ceremony).
- `builder` — required. `env` here is this node's own agent credentials
  (`ANTHROPIC_API_KEY` or whatever the configured agent needs); Foundry
  merges its own `FOUNDRY_*` protocol vars on top (see below) — never the
  other way around, so a bet's own env can't accidentally shadow the
  protocol.
- `max_gate_iterations` — caps builder retries on gate failure. Omit to
  default to `budget.iterations`, or 3 if that's unset too.

## Why the prompt text never mentions the bet

`command` is a **generic invocation of one of the shipped reference
templates** —
[build-loop-test-writer-prompt.md](build-loop-test-writer-prompt.md) and
[build-loop-builder-prompt.md](build-loop-builder-prompt.md) — copied
verbatim into a heredoc, not hand-substituted per bet. Every bet-specific
detail (hypothesis, success metric, protected paths, branch names, prior
gate violations) arrives through env vars Foundry injects at run time:

| Env var                   | Set for             | Meaning                                                                           |
| ------------------------- | ------------------- | --------------------------------------------------------------------------------- |
| `FOUNDRY_BET_SLUG`        | both                | the bet's slug                                                                    |
| `FOUNDRY_HYPOTHESIS`      | both                | the bet's hypothesis text                                                         |
| `FOUNDRY_SUCCESS_METRIC`  | both                | JSON `{name, target?, description?}`                                              |
| `FOUNDRY_PROTECTED_PATHS` | both                | JSON list of protected path prefixes                                              |
| `FOUNDRY_FLAG_KEY`        | both                | `bet-<slug>` — what the builder's change must sit behind                          |
| `FOUNDRY_TARGET_REPO_URL` | both                | `target_repo.url`, already checked out at `FOUNDRY_WORK_BRANCH`                   |
| `FOUNDRY_TARGET_BASE_REF` | both                | `target_repo.base_ref`                                                            |
| `FOUNDRY_WORK_BRANCH`     | both                | branch to commit/push to (test-writer: `bet/<slug>-tests`; builder: `bet/<slug>`) |
| `FOUNDRY_GATE_BASE_REF`   | builder             | what the builder's `artifact_ready.base_ref` must be set to                       |
| `FOUNDRY_GATE_ATTEMPT`    | builder             | 1-indexed attempt number                                                          |
| `FOUNDRY_GATE_VIOLATIONS` | builder, attempt 2+ | JSON list of the previous attempt's `gate.result` violations                      |

This keeps the templates reusable across every build-loop bet with zero
per-bet text substitution — and avoids ever having to interpolate a bet's
free-text hypothesis into a shell command.

## Branch convention (why there's a `-tests` branch)

Foundry clones `target_repo` and checks out the right ref for you (extending
the existing memory-repo-clone pattern) _before_ the agent's command runs:

- **test-writer**: checks out `target_repo.base_ref` fresh. The template
  instructs it to create and push `bet/<slug>-tests` — an **immutable
  baseline**, never touched again after this one run.
- **builder, every attempt**: checks out `bet/<slug>-tests` (or
  `target_repo.base_ref` directly, if there's no test-writer) — **not** the
  previous attempt's commits. A failed attempt never compounds; every retry
  starts from the same clean baseline plus the gate's feedback. The template
  instructs the agent to force-push `bet/<slug>` fresh each time.

This is also what makes `protected_paths` mean the right thing: the
builder's `artifact_ready` sets `base_ref` to the tests baseline
(`FOUNDRY_GATE_BASE_REF`), not the original `target_repo.base_ref` — so the
gauntlet's diff is the builder's changes _only_. The test-writer's own
commit never shows up in a `protected_paths` violation it didn't cause.

## What happens after `artifact_ready`

The builder's `artifact_ready` still triggers the gauntlet exactly the way
any other managed bet's does (`gate_config.checks` non-empty +
`foundry-reviewhog-gate` flag → automatic `foundry-run-gate` run, see
[managed-run-config.md](managed-run-config.md)). `foundry-build-bet` polls
for the resulting `gate.result`:

- **pass** → done. The bet is `gated`.
- **fail** → the next attempt's builder gets `FOUNDRY_GATE_VIOLATIONS`.
- **iterations exhausted** → `run.finished {outcome: "gate_exhausted"}` +
  a note; the bet stays `building` for a human (or `/bet verdict`) to decide
  what happens next — nobody reads the diff to make that call, the gate
  record and the builder's own `knowledge.published` entries are the
  evidence.

`/bet status` renders the attempt count from the `"builder: gate attempt
N/M"` note the workflow emits before each attempt — no schema change needed
to see it.

## Secrets

`builder.env` (and `test_writer.env`) are the **only** place agent
credentials or repo push tokens enter a build-loop node — never typed into
the bet spec's free text, never committed. Foundry redacts any env value
whose _name_ looks like a bare credential (`API_KEY`, `TOKEN`, `SECRET`,
`PASSWORD`, `CREDENTIAL` — case-insensitive) out of every note, knowledge, or
artifact payload before it becomes a BetEvent, even if the agent's own
output echoes it. `target_repo.url` (and `memory_repo_url`) are treated as
operational metadata, not bare credentials — they're expected to appear in
`artifact_ready.repo_url`, the same way `memory_repo_url` already appears on
the bet itself.

## The Claude CLI in the sandbox

Build-loop nodes install `@anthropic-ai/claude-code` via `npm install -g` at
sandbox-startup time — the `slim_base` sandbox template already ships
git+node+uv, and a dedicated image layer would also need mirroring in the
production (Modal) image definition. This costs roughly the time of one
`npm install` (tens of seconds) per node run; if that overhead ever matters,
the next step is a dedicated sandbox template with the CLI baked in.
