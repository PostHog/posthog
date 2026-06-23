# Preview-mode side-effect isolation — state and direction

Preview mode lets an author iterate on a **draft (non-live) revision** in a
sandboxed chat session. The intent: run the agent against real production
**reads** without its **writes** touching the outside world or polluting
observability. This doc records what ships today, why the current approach has
a ceiling, and the decision the team needs to make next.

> **Framing first:** preview is an **authoring-iteration aid**, not a faithful
> end-to-end test. It answers "does my draft gather the right context and
> _decide_ the right action?" — it does **not** prove the action works. The
> docs and UI should say this plainly; a half-true "preview is isolated" claim
> is worse than none, because authors trust it.

## What ships today

Shipped in the preview-isolation work (the `is_preview` signal threaded from the
ingress resolution to the runner):

- **`agent_session.is_preview`** — derived server-side from a verified
  `aud=agent-ingress.preview` JWT against a non-live revision (never
  client-asserted). Immutable for the row's life.
- **Native write tools** (`slack-post-message`/`update`/`react`, mutating
  `http-request`, `memory-write`/`update`/`delete`, `table-append`/`delete`/
  `truncate`) short-circuit in preview via `isPreviewSideEffect(...)`, returning
  a shape-valid synthetic result and logging `tool_preview_skipped`.
- **MCP and custom (sandbox) tools** are suppressed **wholesale** in preview
  (fail-closed) — see below.
- **Analytics**: `$ai_*` events from a preview session carry
  `$agent_is_preview: true`.
- **Mint endpoint**: minting a preview JWT requires `agents:write` on **both**
  verbs (the GET sibling exists only for EventSource and returns the same usable
  token).

## Why the current approach has a ceiling

Isolation today is **suppression** — at the side-effecting call, return a
synthetic result instead of doing the thing. Two structural problems:

1. **Fail-open by construction.** It started as a per-native-tool denylist: any
   write path that doesn't call `isPreviewSideEffect` escapes. A security review
   found exactly this — MCP calls, custom/sandbox tools, and the PostHog-API
   management tools were all ungated. We closed those (MCP + custom are now
   suppressed wholesale), but "remember to gate the next write path" is not a
   property you can rely on.

2. **Suppression can't be both safe and faithful.** Suppress a write and the
   model's next turn reasons over a fabricated result — so multi-step chains
   diverge from reality. Don't suppress and real writes fire. There's no setting
   of the dial that gives you both.

### HTTP method is not a read/write signal

The obvious "gate writes centrally by HTTP method" does **not** work here.
Every `@posthog/*` tool routes through one `callPosthogApi` helper, so gating
mutating methods there looks like a clean one-line fix — but **`posthog-query`
runs HogQL via `POST` and is a read.** Method-based gating would suppress query
execution in preview and destroy the real-reads value, which is the one thing
preview is actually good for.

This is why the remaining PostHog-API management-write gap (create / partial-
update / promote / freeze / archive / revision create+update, etc.) is **not**
closed yet: the safe fix needs a real per-endpoint read/write classification,
not a method heuristic. MCP has the same problem — `readOnlyHint` is advisory
and untrusted, so we currently suppress all MCP calls (blinding MCP reads too).

## The decision

Two real directions (not mutually exclusive):

### A. Explicit read/write classification + central fail-closed gate

Add a first-class read/write classification to native tool defs (default:
write), plumb MCP `readOnlyHint`, and gate once at the dispatch boundary —
default-deny writes in preview. Structurally fail-closed; closes every current
and future path.

- **Cost:** every tool/endpoint must be classified (and kept classified). MCP
  hints are untrusted, so unclassified MCP reads stay suppressed — the real-
  reads value degrades exactly where agents lean on MCP.

### B. Sandbox-real side effects

Stop suppressing. Route writes to **disposable targets** — a scratch Slack
channel, temp tables, a throwaway memory namespace, a sandbox API account — so
the chain runs **for real but harmlessly**.

- **Upside:** dissolves the finding class _and_ the safe-vs-faithful trade —
  nothing is faked, so multi-step chains stay honest.
- **Limit:** not every external system has a safe target (an arbitrary customer
  API has no "scratch" account).

### Recommendation: hybrid

Sandbox-real wherever a disposable target exists; fail-closed suppression
(approach A) only as the backstop for writes with no safe target. And regardless
of approach, **reframe preview in the product as an iteration aid, not a test.**

## Tracked debt

- [ ] PostHog-API management **write** tools ungated in preview (needs read/write
      classification, not method gating — see above). Severity: low.
- [ ] MCP suppression is wholesale (blinds reads). Replace with classification
      or sandbox-real.
- [ ] Custom/sandbox tool suppression is wholesale (blinds reads). Same.
- [ ] Decide A vs B vs hybrid; then implement once, at the dispatch boundary.
