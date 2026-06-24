# Skill — running mocked ("preview") runs

How to drive a **real conversation against an agent with side effects
suppressed** — the platform calls this a "preview" run, but the honest
name is a **mocked run**: the model loop, prompts, skills, read tools
and approvals all run for real; only the things that touch the outside
world are faked.

Load this whenever you want to TRY an agent before promoting, or
REPRODUCE a live agent's behavior to debug it, without firing real
writes into Slack / webhooks / external services.

> **Naming:** "preview" is a misnomer kept for wire/schema
> compatibility (`agent_session.is_preview`, `$agent_is_preview`). It
> does NOT mean "a draft revision." It means "this run's side effects
> are mocked." A mocked run can target a draft OR the live revision.
> When talking to the user, say "a mocked run (no real side effects)" —
> don't let "preview" imply it only works on drafts.

## What runs for real vs what's mocked

| Surface                                                              | In a mocked run                                                                                                |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Model loop, system prompt, skills, reasoning                         | **Real**                                                                                                       |
| Read-only native tools (`@posthog/query`, slack-read-\*)             | **Real** — hit live data                                                                                       |
| Read-only MCP tools (annotated `readOnlyHint: true`)                 | **Real** — hit the live server                                                                                 |
| Write/destructive MCP tools (or UNANNOTATED ones)                    | **Mocked** — synthetic `{ preview_skipped: true }`, fail-closed                                                |
| Custom (sandbox) tools                                               | **Mocked** — no read/write signal, so all suppressed                                                           |
| `@posthog/slack-post-message`, webhook delivery, other write natives | **Mocked** — synthetic success                                                                                 |
| Approvals                                                            | **Real** — gated tools still queue (then the underlying call is mocked)                                        |
| Analytics                                                            | **Real but tagged** — every `$ai_*` event carries `$agent_is_preview: true` so it stays out of prod dashboards |

Key consequence: **reads are real.** A mocked run of an agent that
reads a customer's PostHog data will read the real data — it's safe
because nothing is written back, not because nothing is touched. Say so
if the agent reads anything sensitive.

## When to offer a mocked run

- **Authoring a new agent** (`authoring-new-agents`, phase 8): before
  the first promote, offer to drive a representative input against the
  `ready` draft so the user sees real behavior, not just passing test
  cases.
- **Editing an agent** (`editing-agents-safely`, step 6): the same, as
  the "manual" half of testing a `ready` revision.
- **Debugging a live agent** (`debugging-sessions`): when a live
  session misbehaved and you want to reproduce it, run the SAME input
  against the **live revision** in mocked mode. You get the real
  decision path (real reads, real prompt) without re-firing whatever
  real write caused the original blast radius.

Always offer; never auto-run a mocked session without the user asking
or agreeing — it consumes model tokens and reads live data.

## How to run one

Two MCP tools, both already on your allow-list. Neither is
approval-gated — a mocked run has no real side effects, so there's
nothing to gate (contrast promote / archive / destroy).

### Option A — `agent-applications-preview-proxy` (default)

One call. Django mints the short-lived preview token server-side,
forwards to the agent ingress, and streams the agent's response back.

- `rest`: `run` to start, `send` to continue, `cancel`, `listen` (SSE tail).
- `revision_id`: the target revision. A draft/ready revision id, **or
  the live revision id** for a mocked run of the live agent.
- body: `{ "message": "<the representative input>" }` for `run`;
  `{ "session_id": "<id>", "message": "..." }` for `send`.

The session it creates has `is_preview = true`. Read it back with
`agent-applications-sessions-retrieve` / `-session-logs` like any other
session — the conversation, tool calls, and `tool_preview_skipped` log
entries tell you exactly which writes were mocked.

Caveat: the proxy strips the caller's auth, so it can't impersonate a
specific end user. Fine for agents with public auth or where you're
just exercising the logic; use Option B if the agent needs the asker's
identity.

### Option B — `agent-applications-preview-token-mint` (direct)

Returns `{ token, expires_in, ingress_slug, endpoints, auth }`. Use
when you need to hit ingress directly (e.g. carrying a specific
identity) rather than through the Django proxy. Attach the token as the
`x-agent-preview-token` header (or `?preview_token=` for EventSource).
`ingress_slug` is `<slug>-<revision-hex>`; `endpoints` lists the
per-trigger URLs so you don't have to construct them.

## Reading the result

After the run, retrieve the session and surface to the user:

- The agent's actual reply / output.
- Which tools ran for real (reads) and which were mocked — the
  `tool_preview_skipped` log entries name each suppressed tool.
- Anything that WOULD have happened in a live run ("it would have
  posted this to #alerts") so the user can judge the real behavior.

Then offer the next step: promote (for an authoring/edit flow), or a
fix proposal (for a debug flow). A clean mocked run is good evidence
but not a substitute for the scripted test cases in
`running-and-evaluating-tests` — recommend both for a non-trivial
change.
