# Design — MCP-driven agent authoring flow

**Status:** speculative design / aspirational. **Owner:** ben.

This doc describes the end-to-end experience of an authoring AI (Claude, etc.)
building a deployable agent on this platform — discover, design, iterate, test,
promote. It maps every step to (a) what already exists in the codebase, (b)
what's stubbed but unfinished, (c) what we'd need to build. The doc closes
with an example **authoring skill** — a markdown file an authoring AI would
load via `@posthog/load-skill` to learn the workflow.

The flow has four hard constraints that drive the design:

1. **The authoring AI sees no raw secrets.** API keys, OAuth tokens, etc.
   are entered by the user in a PostHog UI form; the MCP only ever receives
   "key present" / "key absent" signals.
2. **Iteration is fast.** Edit-test loop should be measured in seconds, not
   minutes. The authoring AI can re-run the agent against a scripted
   conversation and inspect the full trace.
3. **Tests don't have side effects.** A test of a Slack-posting agent
   doesn't post to a real Slack channel. A test of an email tool doesn't
   email a real user. Egress is mocked or sandboxed.
4. **The authoring AI can self-evaluate.** Give it the full conversation
   trace + tool-call log + expectations and it can grade its own work
   before promoting.

---

## 1. The flow at a glance

```text
DISCOVER          DESIGN              CONFIGURE        AUTHOR          TEST             PROMOTE
─────────         ──────              ─────────        ──────          ────             ───────
list catalogs  →  draft a spec     →  punch-out for →  write/edit  →   scripted   →     freeze
                                       secrets         bundle files     conversations    promote
load authoring                                                         + self-eval
skill                                                                  + iterate
```

Each phase has a well-defined contract with the MCP. The authoring AI never
holds long-running state — every step is a stateless MCP call.

---

## 2. Detailed walkthrough

### Phase 1 — discover

The authoring AI starts by loading the **authoring skill** (full text below in
§6). This skill explains the platform: what an agent is, what tools exist,
what skills are, how the spec is structured, common patterns. The skill is
authored once by PostHog and versioned; we serve it as a template (see C5 in
`plans/skill-templates.md`).

The AI then enumerates the building blocks available:

| Call                                            | What it returns                                                        |
| ----------------------------------------------- | ---------------------------------------------------------------------- |
| `agent-authoring-skill-retrieve` _(new)_        | The authoring skill markdown body                                      |
| `agent-native-tools-list`                       | Every `@posthog/*` tool: id, description, args schema, required scopes |
| `agent-skill-templates-list` _(new — C5)_       | Library skills the team can import by reference                        |
| `agent-custom-tool-templates-list` _(new — C5)_ | Library custom tools the team can import by reference                  |
| `agent-applications-list`                       | Existing agents in the team (for cloning)                              |

These return cheap catalog data — the AI doesn't need to do anything except
read what's available before committing to a design.

### Phase 2 — design the spec

Based on the user's brief, the AI drafts an `AgentSpec` (the JSON shape in
`services/agent-shared/src/spec/spec.ts`):

```jsonc
{
  "model": "anthropic/claude-sonnet-4-6",
  "triggers": [{ "type": "slack", "config": { "trusted_workspaces": ["T01ABC"] } }],
  "tools": [
    { "kind": "native", "id": "@posthog/query" },
    { "kind": "native", "id": "@posthog/slack-post-message" },
    { "kind": "custom_template", "from_template": "<uuid>", "alias": "stripe_lookup" },
    { "kind": "custom", "id": "in-app-helper", "path": "tools/in-app-helper/" },
  ],
  "skills": [
    { "from_template": "<uuid>", "alias": "research", "description": "How to research a question" },
    { "id": "in-app-context", "path": "skills/in-app-context.md", "description": "Our product taxonomy" },
  ],
  "secrets": ["STRIPE_API_KEY"],
  "limits": { "max_turns": 30, "max_tool_calls": 100, "max_wall_seconds": 300 },
}
```

The AI validates every `tool.id` against the catalog from phase 1 and
every `from_template` against the templates catalog. Validation happens
in-context (no API call) — fail fast.

### Phase 3 — configure secrets (the punch-out)

This is the most important design constraint. **The authoring AI cannot
receive raw secret values.**

Today, `agent-applications-set-env-create` accepts the env block as JSON in
the request body. That means an MCP-driven flow would force the user to
paste secrets at the AI, which then forwards them. Wrong shape.

Replacement flow:

1. AI calls **`agent-applications-secrets-issue-write-token`** _(new)_:

   ```jsonc
   { "application_id": "...", "keys": ["STRIPE_API_KEY", "SLACK_TOKEN"] }
   ```

   The server (Django) generates a signed, single-use, short-lived
   (15min) token scoped to `(team_id, application_id, key_names)`. It
   returns a UI URL like
   `https://app.posthog.com/agents/<slug>/secrets?token=<sig>`.

2. AI tells the user: _"Please open this link and enter your Stripe API
   key + Slack token. I'll continue when you're done."_

3. User opens the URL, hits a PostHog form that shows just the requested
   key names with empty password-type inputs. They type the values, hit
   save. The form posts to a Django endpoint that:
   - Verifies the token
   - Encrypts each value with the team's Fernet keys
   - Upserts into `agent_application.encrypted_env`
   - Marks the token used

4. AI polls **`agent-applications-secrets-status`** _(new — read-only,
   returns just key names + a "set_at" timestamp; no values)_:

   ```jsonc
   {
     "keys": [
       { "name": "STRIPE_API_KEY", "is_set": true, "set_at": "2026-05-28T10:31Z" },
       { "name": "SLACK_TOKEN", "is_set": true, "set_at": "2026-05-28T10:32Z" },
     ],
   }
   ```

5. Once all required keys are set, the AI continues.

For team-wide integrations (Slack OAuth, Stripe Connect, etc.) the model
adds `requires_integration: <kind>` instead of declaring a secret name. The
team already has the integration installed, and the runner resolves it
from the integrations table at session start (this part exists in v1's
ingress flow; v2 deferred wiring).

### Phase 4 — author the bundle

Now the AI builds the actual agent bundle (`agent.md`, skills/_, tools/_).
This is the part that's largely **already implemented** by the work done
this session:

| Step                                                 | Existing MCP tool                                            |
| ---------------------------------------------------- | ------------------------------------------------------------ |
| Branch a fresh draft from the live revision          | `agent-applications-revisions-new-draft-create`              |
| Pull the existing bundle to edit holistically        | `agent-applications-revisions-bundle-retrieve`               |
| Write one file at a time (skill, tool source)        | `agent-applications-revisions-file-update`                   |
| Bulk push after a complex edit                       | `agent-applications-revisions-bundle-update` (mode: replace) |
| Inspect what's in the bundle without pulling content | `agent-applications-revisions-manifest-retrieve`             |

For custom tools the AI writes the TS source under `tools/<id>/source.ts`
plus a `tools/<id>/schema.json` declaring the args shape and any required
secrets via `secrets: ["FOO"]` (so when the model imports it the
build-time tooling can verify the secret was declared on the spec).

We'd add **`agent-applications-revisions-validate`** _(new)_ to surface
structural problems before freeze:

- Parse spec against `AgentSpecSchema` (the zod schema) — same parse the
  runner does
- Every tool id resolves to a native tool or a template or a bundle path
- Every `secrets[]` name has a matching env key (set via the punch-out)
- Every skill referenced in `agent.md` exists in the bundle
- No `..` / absolute paths in tool sources
- Warnings: skills declared but never referenced; tools in bundle but
  not in spec

Validation returns `{ ok, errors: [], warnings: [] }`. The AI fixes
errors and re-runs.

### Phase 5 — freeze + test

Freezing today does what the runner needs: computes the bundle sha256,
stamps the row, flips state `draft → ready`. But **you can't run a `ready`
revision against a scripted conversation today** — promoting it would make
it live for real triggers.

We'd add a separate concept: **test runs**.

#### Test sessions

A "test session" is a normal session except:

- Lives in a `agent_test_session` table (separate from `agent_session`),
  auto-cleaned after 24h
- Wears a `is_test=true` flag the runner reads at session start
- Sandboxes provisioned with **egress mocked**:
  - `@posthog/web-fetch` returns fixture responses (the test spec can
    declare fixtures)
  - `@posthog/slack-*` becomes a no-op that logs the call
  - Custom tools that talk to external APIs get sandboxed via a network
    proxy that rejects non-fixture hosts
- Secrets are still real (we want to test the auth path works) BUT egress
  controls mean they never reach real Stripe / Slack
- Sessions count against a separate test-quota, not the agent's quota

#### Test spec

The AI defines what "good" looks like:

```jsonc
{
  "name": "happy path — user asks for sales numbers",
  "trigger": {
    "type": "chat",
    "messages": [{ "role": "user", "content": "What were our top 5 products last week?" }],
  },
  "expected": {
    "tool_calls_include": ["@posthog/query"],
    "tool_calls_exclude": ["@posthog/slack-post-message"],
    "assistant_text_matches": "^(Top|The top) (?:5|five)",
    "max_turns": 5,
    "must_complete_within_ms": 30000,
  },
}
```

Multiple test cases live alongside the bundle at `tests/*.json`. The AI
adds them via the same file-write API.

#### Running the tests

| MCP tool                                                     | Action                                                                                               |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| `agent-applications-revisions-test-run` _(new)_              | Run one or all tests; returns `test_run_id`                                                          |
| `agent-applications-revisions-test-results-retrieve` _(new)_ | Poll for results: full conversation, tool call log, pass/fail per assertion, token usage             |
| `agent-applications-revisions-test-replay-retrieve` _(new)_  | Get the underlying session trace as messages (same shape as the runtime conversation, but read-only) |

#### Self-evaluation

The really cool bit: the authoring AI can grade its own work. Test results
include:

```jsonc
{
    "test_run_id": "...",
    "cases": [
        {
            "name": "happy path",
            "passed_assertions": ["tool_calls_include", "must_complete_within_ms"],
            "failed_assertions": ["assistant_text_matches"],
            "conversation": [...],
            "tool_calls": [...],
            "logs": [...],
            "usage": { "input_tokens": 1234, "output_tokens": 567, "cost_usd": 0.012 }
        }
    ]
}
```

The authoring AI inspects the failures, edits the bundle (probably the
`agent.md` instructions or a skill), re-freezes (more on this in §4), re-tests.

For squishier evaluations ("does the response sound friendly?") the AI can
call a **judge skill** — itself another agent on the platform whose job is
to read another agent's conversation and grade it. The judge agent is
authored the same way; we eat our own dogfood.

### Phase 6 — promote

After test passes the AI calls
`agent-applications-revisions-promote-create`. The previously-live revision
is auto-archived; future Slack mentions / chat triggers hit the new code.

For higher-stakes agents we'd want a **preview-link** intermediate:
**`agent-applications-revisions-issue-preview-link`** _(new)_ generates a
signed URL that lets a specific human (the user, a manager) trigger the
_ready_ revision via chat — same as live but only callable through that
URL. The user kicks the tires manually, then signs off.

---

## 3. Recap — what we have vs what we'd need

### Already implemented (this session + earlier)

| Capability                                                                                | Where                                                                  |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Native tool catalog endpoint                                                              | `agent-janitor /native_tools` proxied by `agent-native-tools-list`     |
| Skill bodies served on-demand via `@posthog/load-skill`                                   | Runner-side B1                                                         |
| Bundle manifest + per-file CRUD + bulk pull/push                                          | Janitor `/revisions/:id/*` proxied by `agent-applications-revisions-*` |
| Freeze (draft → ready + sha256 stamp)                                                     | Janitor `/revisions/:id/freeze`                                        |
| Clone bundle from another revision                                                        | Janitor `/revisions/:id/clone_from`                                    |
| Promote (ready → live)                                                                    | Django `promote` action                                                |
| Encrypted env at rest + decrypted at runtime (no raw secrets in model context AT RUNTIME) | `EncryptedFields` + `SecretBroker`                                     |
| Sandboxed custom tools with nonce-substituted secrets                                     | `SecretBroker.mintSessionMap()` + the sandbox host                     |
| Cross-host SSE for live trigger observation                                               | `RedisSessionEventBus`                                                 |

### Stubbed / partial

| Capability                                 | Status                                                  |
| ------------------------------------------ | ------------------------------------------------------- |
| Templates library (skills + tools)         | Designed in `plans/skill-templates.md`, no code         |
| Runtime third-party MCPs                   | Designed in `plans/runtime-mcps.md`, no code            |
| Prior-log loading from CH for old sessions | Designed in `plans/resumable-conversations.md`, no code |
| Docker sandbox in production               | Code done, image not published to ghcr                  |

### To build

The new MCP tools / Django actions required by this design:

| Tool                                                 | Action                                                | Replaces                            |
| ---------------------------------------------------- | ----------------------------------------------------- | ----------------------------------- |
| `agent-authoring-skill-retrieve`                     | Returns the authoring skill markdown                  | hard-coded knowledge                |
| `agent-applications-secrets-issue-write-token`       | Mint a signed punch-out URL                           | accepting raw secret values via MCP |
| `agent-applications-secrets-status`                  | Lists key names + set_at, no values                   | inferring from `set_env` body       |
| `agent-applications-revisions-validate`              | Pre-freeze structural check                           | runner-side late failures           |
| `agent-applications-revisions-test-run`              | Kick off a test run                                   | manual real-trigger testing         |
| `agent-applications-revisions-test-results-retrieve` | Poll for results + assertions                         | nothing                             |
| `agent-applications-revisions-test-replay-retrieve`  | Read the test session trace                           | nothing                             |
| `agent-applications-revisions-issue-preview-link`    | Sign a URL the user can use to drive `ready` manually | promoting first to check live       |

Supporting infrastructure:

- **PostHog UI**: a `/agents/<slug>/secrets?token=...` page that renders just
  the requested key inputs and submits to a token-bound endpoint.
- **`agent_test_session` table** in the agent DB + a runner branch that
  uses it instead of `agent_session`. Or simpler: reuse `agent_session`
  with `is_test boolean` and a separate cleanup policy on the janitor.
- **Egress proxy** for test sandboxes: a per-test policy file declares
  what hosts get mocked (return fixtures) vs blocked vs passed through.
- **Test quotas / rate limit** so a buggy authoring AI doesn't burn the
  whole team's model budget on test runs.

---

## 4. Open questions

1. **Where do tests live in the bundle vs the spec?** Spec wants to be the
   structural truth; bundle wants to be the content. Tests are content but
   spec-bound. Probably `tests/*.json` in the bundle, with a top-level
   `tests` field in spec that points at them.
2. **Can a `ready` revision be tested without going back to draft?** Today
   freezing is one-way and tests against a frozen revision can't mutate
   the bundle. Two options: (a) test-runs against draft (which means the
   sha256 isn't pinned — fine for tests, but a re-test after edits needs
   the manifest), (b) snapshot the draft into a frozen-but-test-only
   revision per test run.
3. **How does the judge skill compose?** A meta-agent that judges other
   agents needs the test results as input. Simplest: it's a regular agent
   we trigger via a webhook with the results JSON; it grades and writes a
   verdict back via the API. Adds a moving part but reuses everything.
4. **Cost cap on test runs**? Especially with judge-evaluation, a single
   test cycle could fire 2-3 LLM calls per case. Hard cap at $X / team /
   day; surface the cap in the test-results response.
5. **Real-world fixtures**: how does the AI know what a Slack message body
   looks like, or what a Stripe customer object looks like, to write
   fixtures? Pre-shipped fixture library per native tool. Same template
   model as skills — the catalog includes example fixtures.
6. **Live-debugging**: when the AI's design is "almost right" can it
   attach to a running test session and see events stream? Today the
   `/listen` SSE bus would let you tail; we'd need an MCP-friendly
   polling adapter or surface raw events through the test-results-retrieve
   endpoint.

---

## 5. Phasing

The minimum viable build to make this real:

**v0.1 — punch-out secrets + basic test runs**

- Secrets issue-write-token + status endpoints
- PostHog UI form (one page, no fancy state)
- Test runs against `is_test=true` sessions
- Egress proxy with a hardcoded mock list for `@posthog/slack-*` and
  `@posthog/web-fetch`
- Test results retrieve

**v0.2 — assertions + preview link**

- Test spec JSON schema, assertion runner
- Preview link issuance + a `/preview/<slug>/<sig>` ingress route
- Validate endpoint

**v0.3 — judge skills + cost caps**

- Judge-skill convention (it's just an agent; ship one canonical one)
- Per-team test budget
- Fixture library

**v0.4 — templates layer (C5)**

- Skill / custom-tool templates so the authoring skill itself can be
  shipped as a template and updated centrally

Each phase ships a working slice of the flow. v0.1 alone unlocks the
"authoring AI builds an agent end-to-end without seeing secrets" promise.

---

## 6. Example output — the authoring skill

This is the skill body that lives at (eventually) `@posthog/authoring`
in the templates library. An authoring AI loads it via
`agent-authoring-skill-retrieve` and reads it before doing anything else.
The skill is what makes the AI competent on this platform — it's the
domain knowledge that doesn't change between agents.

````markdown
# Authoring agents on the PostHog agent platform

You are building an agent. Read this whole skill before writing any code.

## What an agent is

An _agent_ (more precisely: an `AgentApplication`) has:

- A **spec** (JSON): the model, triggers, tools, skills, limits, secrets it
  needs. The spec is structural — it's how the runner decides what to run.
- A **bundle** (filesystem-like): `agent.md` (the system prompt), `skills/*`
  (markdown the model can load on demand), `tools/*` (custom code that
  runs in a sandbox).
- A **state machine of revisions**: every change is a new revision in
  state `draft` → `ready` → `live`. Live is what production traffic hits.

You will be operating on a _draft_ revision. Drafts are mutable. Once
you `freeze` a draft it becomes `ready` — bundle + spec are immutable —
and you can `promote` it to `live`.

## The mental model

Think of yourself as a tech lead writing a new microservice. The spec is
the deployment config; the bundle is the code; the runner is k8s. You
write tests, run them in a sandbox, fix what breaks, then ship.

Do NOT try to do everything in one call. The MCP gives you small,
composable verbs. Use them.

## The hard rules

1. **You cannot see raw secrets.** When an agent needs an API key, you ask
   the platform to mint a punch-out URL; the user enters the key in a
   PostHog form; you never see the value. Always.
2. **Tests don't have side effects.** Use the test-run path, not real
   triggers, until you're confident the agent works.
3. **Validate before freezing.** The validate endpoint catches structural
   issues (wrong tool id, missing skill referenced from agent.md, etc.) in
   seconds. Use it.
4. **Freeze is one-way.** If you freeze something broken you have to
   create a new draft and start over. Test thoroughly first.

## The flow

### 1. Understand what's available

```
agent-native-tools-list                  # what built-in tools exist
agent-skill-templates-list               # what reusable skills exist
agent-custom-tool-templates-list         # what reusable custom tools exist
agent-applications-list                  # what agents already exist (to clone from)
```

Read carefully. Don't invent tool ids — every `tool.id` in your spec must
appear in one of these catalogs (native, custom template, or bundle path).

### 2. Decide if you're branching or starting fresh

If you're editing an existing agent: use `agent-applications-revisions-new-draft-create`
with the current live revision id. You get a draft already populated with
the live bundle.

If you're creating new: `agent-applications-create` then
`agent-applications-revisions-create` for an empty draft.

### 3. Design the spec

The spec lives in JSON. The minimum:

```json
{
  "model": "anthropic/claude-sonnet-4-6",
  "triggers": [{ "type": "chat", "config": { "require_auth": true } }],
  "tools": [{ "kind": "native", "id": "@posthog/query" }],
  "skills": [],
  "secrets": [],
  "limits": { "max_turns": 30, "max_tool_calls": 100, "max_wall_seconds": 300 }
}
```

Patch it via `agent-applications-revisions-partial-update`. Spec is
mutable while state=draft.

### 4. Wire secrets

If your spec lists `secrets: ["FOO"]`, the user has to provide a value
before the agent can run. Don't ask them to paste it at you. Instead:

```
agent-applications-secrets-issue-write-token  →  returns { url, expires_at }
```

Then tell the user:

> Please open <url> and enter your FOO. I'll continue once that's done.

Poll `agent-applications-secrets-status` every 5-10 seconds until
`is_set: true` for every key in your spec.

### 5. Write the bundle

Use file-level edits for surgical changes (one skill, one tool source)
and the bulk bundle PUT for big rewrites.

Conventions:

- `agent.md` — the system prompt. Keep it short; let skills carry depth.
- `skills/<id>.md` — one skill per file. Each skill has a one-line
  description in the spec; the description is what makes the model decide
  whether to load it via `@posthog/load-skill`.
- `tools/<id>/source.ts` — your custom tool's TypeScript source.
- `tools/<id>/schema.json` — args shape + required secrets:
  ```json
  { "description": "...", "args": { ... }, "secrets": ["FOO"] }
  ```

When you write a custom tool, declare its `secrets` in the schema so
validation catches missing wiring.

### 6. Validate

```
agent-applications-revisions-validate
```

Returns `{ ok, errors, warnings }`. Fix every error. Warnings are
optional but worth reading — unused skills, dangling references, etc.

### 7. Write tests

Put test specs at `tests/*.json` in the bundle. One file per case:

```json
{
  "name": "user asks for sales numbers",
  "trigger": {
    "type": "chat",
    "messages": [{ "role": "user", "content": "What were our top 5 products last week?" }]
  },
  "expected": {
    "tool_calls_include": ["@posthog/query"],
    "tool_calls_exclude": ["@posthog/slack-post-message"],
    "assistant_text_matches": "^(Top|The top) (?:5|five)",
    "max_turns": 5,
    "must_complete_within_ms": 30000
  }
}
```

Aim for 3-5 cases covering happy path + obvious edge cases + a hostile
input. Don't try to enumerate everything.

### 8. Freeze and run tests

```
agent-applications-revisions-freeze-create     # draft → ready, stamps sha256
agent-applications-revisions-test-run          # runs every tests/*.json
```

Poll `agent-applications-revisions-test-results-retrieve`. You'll get
back the full conversation, tool call log, assertion results, and token
usage per case.

### 9. Self-evaluate

Read the conversations. Did the agent do what you expected? Are the tool
calls the right ones, in the right order, with the right args? Is the
final response coherent and on-topic?

For squishier judgments, invoke the judge skill agent — it reads the
test results and grades them on a rubric. (If no judge agent exists for
your team, skip this step.)

If anything is wrong:

- **Wrong tool choice**: edit `agent.md` to be more directive about
  which tool to use when.
- **Wrong tool args**: edit the relevant skill body to give better
  examples.
- **Missing capability**: edit the spec to add a tool / skill.
- **Wrong final response**: usually a system-prompt issue — sharpen
  `agent.md`.

Then create a fresh draft from this revision (`new-draft-create`), apply
your fixes, freeze, re-test. Don't try to edit the frozen revision.

### 10. Optional preview

For high-stakes agents, before promoting:

```
agent-applications-revisions-issue-preview-link
```

Send the URL to the user. They drive a real conversation against your
_ready_ revision — same code, same model, same tools — except it only
responds to that signed URL, not real triggers. If they're happy, you
promote.

### 11. Promote

```
agent-applications-revisions-promote-create
```

The previously-live revision is auto-archived. Your new revision now
serves real triggers.

## Common pitfalls

- **Inlining secrets in agent.md or tool source**. They don't work
  (they're plaintext, not nonces) AND they leak into the model context.
  Always declare in spec.secrets and read via ctx.secrets.ref(name).
- **Forgetting `description` on a skill**. The model doesn't load skills
  it doesn't know it needs — the description in the spec is its only
  signal.
- **Building a one-shot mega-tool**. Native tools are designed to compose.
  Two small tools with clear contracts beat one tool with 12 args.
- **Skipping the validate step**. The runner WILL surface the error,
  but only after burning a model call. Validate is free.
- **Not testing failure modes**. Write at least one test where the
  expected behavior is `end_session` with an error or `ask_for_input`.

## Things to remember

- This is a generative product. Aim for "good enough to ship, with tests
  covering the obvious failure modes" rather than "provably correct".
- The user is the source of truth for what success looks like. When
  uncertain, ask them — don't guess at intent.
- Every revision is an audit record. Don't be afraid to make many
  revisions; archive the ones that didn't work but keep the trail.
````
