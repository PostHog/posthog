# Design — agent console website (read-mostly UI + agent-mediated editing)

**Status:** draft. **Owner:** ben.

> The MCP gives the authoring AI a complete surface. Humans don't have
> one yet — today the only way to inspect an agent (spec, bundle,
> revisions, sessions, logs) is to either drive the MCP directly or
> read JSON out of `psql`. This plan adds a standalone website that
> renders all of that, and folds the editing flow into a single chat
> with a concierge agent rather than a wall of forms.

## 1. Problem

Three audiences need a UI today:

1. **Operators** debugging a misbehaving agent — "show me what
   `weekly-digest` actually has shipped, what its last 10 sessions
   did, where they failed".
2. **Authors** iterating on an agent — "let me see the current spec,
   tweak the system prompt, kick off a test, watch it stream, promote
   if it works".
3. **Reviewers** approving a draft a teammate / authoring-AI built —
   "show me what changed between live and this draft, let me chat to
   the candidate, then I'll promote".

Today (1) and (3) have **no UI at all**, and (2) is a JSON-pasting
exercise against the MCP. The platform's primitives are all there —
spec, bundle, revisions, sessions, SSE — but nothing surfaces them
to a human.

Building a traditional forms-and-buttons admin would re-invent
half of what the authoring AI already does well. The interesting
shape is to keep the **read** experience traditional (HTTP + REST +
React + design tokens) and route every **write** through a chat
session with a concierge agent.

## 2. Shape at a glance

```text
                  ┌────────────────────────────────┐
                  │   agent-console (Next.js app)  │
                  │                                │
                  │   ┌───── read panel ─────┐     │
                  │   │ spec / agent.md      │     │
       Browser ──►│   │ skills / tools       │     │
                  │   │ revisions, sessions  │     │
                  │   │ logs, traces         │     │
                  │   └──────────────────────┘     │
                  │                                │
                  │   ┌─ <AgentChat /> dock ─┐     │
                  │   │ from @posthog/       │     │
                  │   │   agent-chat (§11)   │     │
                  │   └──────────────────────┘     │
                  └────────────────────────────────┘
                              │                │
                  read calls  │                │  SSE + send
                              ▼                ▼
                  PostHog Django REST   agent-ingress
                       /api/...            /chat/...
                              │                │
                              ▼                ▼
                          Postgres        concierge agent
                                          (deployed in PostHog
                                           org's account, session
                                           principal = user)
                                                │
                                                ▼
                                          MCP tools  →  same API
                                                        endpoints
                                                        as read side
```

Reading is boring CRUD against the REST API. Editing is one chat
session with the concierge, which calls the same MCP tools the
authoring AI already uses. The chat surface itself is a separate
package the console _embeds_ (§11) — so anything else that wants
to talk to an agent later can drop the same dock in.

## 3. Why a separate service, not part of frontend/

Three reasons to live outside `frontend/`:

1. **Standalone deploy.** The console should be runnable against any
   PostHog cloud region (or eventually self-hosted), without dragging
   the entire main webapp in. Same DNS rules apply as the rest of
   the agent platform (`*.agents.posthog.com`).
2. **Different lifecycle.** The agent platform iterates on a faster
   cadence than the main product surface. Coupling deploys would
   slow both sides.
3. **No kea, no PostHog frontend conventions.** The agent platform
   already has its own type system (zod everywhere) and its own
   service shape. Putting the console under `services/agent-console/`
   keeps it in the platform's idiom — typed config loader, OpenAPI-
   generated client, no Django sprawl.

This is **not** a long-term commitment. If the console ever becomes
the right entry point for the broader PostHog UI, or if we want a
chat dock natively inside `app.posthog.com`, the chat package (§11)
makes that move cheap.

## 4. Tech choices

| Concern        | Choice                                                                                                                                                                                                                                                                            |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Framework      | **Next.js (app router)**. SSR for the read pages (cheap, cacheable). Client components for chat + focus-tool wiring. Static export possible later if we want a pure-edge deploy.                                                                                                  |
| Design system  | **[`@posthog/quill`](../../../packages/quill)**. Already styled, already themed, already in this repo. Tailwind v4 wiring per the quill README. Dark / light via `ThemeProvider`. No bespoke component library — every surface composes quill primitives.                         |
| Chat surface   | **`@posthog/agent-chat`** (§11) — a new package this plan introduces, sibling to quill. The console embeds `<AgentChat />`; it doesn't re-implement the dock.                                                                                                                     |
| Auth           | **PostHog OAuth**, brokered through the existing [`services/oauth-proxy/`](../../../services/oauth-proxy) (`oauth.posthog.com`). Same flow customers use for third-party integrations. Console is just another OAuth client; user's session cookie carries a scoped access token. |
| API client     | **Generated TypeScript client** from PostHog's OpenAPI spec (`hogli build:openapi` output, same pipeline as MCP). No hand-written `fetch` wrappers. Endpoints we read live under `/api/projects/<team>/agent_applications/*`.                                                     |
| Streaming      | **`EventSource` against `agent-ingress` `/listen`**, plumbed through the existing `RedisSessionEventBus`. Implementation lives inside `@posthog/agent-chat` (§11); the console doesn't see SSE directly.                                                                          |
| Service layout | `services/agent-console/` alongside ingress / janitor / runner / mcp. Typed config loader per `typed-config-loader.md`. Dockerizable later; v0 runs locally via `pnpm dev` and can deploy to Vercel or our own infra without re-architecting.                                     |

## 5. Auth — PostHog OAuth (not embedded)

The console is a standalone OAuth client of PostHog, not an embedded
view inside `app.posthog.com`. The user lands on
`console.agents.posthog.com` (or `localhost:3040` in dev), hits "log
in", gets redirected through `oauth.posthog.com`, comes back with a
scoped access token, then picks an organization + project from the
list their token has access to.

Scopes requested by the console:

- `agent_application:read` — read every endpoint listed in §6.
- `agent_session:read` — list and tail sessions.
- `agent_application:write` — **not requested directly**. The console
  itself never writes. Writes happen through the concierge agent's
  session principal, which carries its own auth (§7).

The OAuth token lives in an HTTP-only cookie on the console origin.
SSR pages read it server-side; client components hit a thin
console-origin `/api/posthog/*` proxy that forwards to the PostHog
REST API with the bearer attached. No PostHog token ever reaches
client JS.

**Why not embed in `app.posthog.com`?** Two reasons:

- The console is the natural shape for the OSS / self-hosted user
  who runs the agent platform without the rest of PostHog. Coupling
  to `app.posthog.com`'s shell forecloses that.
- The agent platform's URL space (`*.agents.posthog.com`) is already
  separate. Putting the console under the same DNS root keeps the
  mental model consistent.

If we ever want a "view this agent in the main PostHog UI" entry
point later, the chat package (§11) drops in directly and the read
pages can be ported as kea logics against the same REST API.

## 6. Read surfaces (the bulk of v0)

Every page renders one or more existing API responses. No
proprietary aggregation — if the MCP can fetch it, the console can
fetch it.

| Route                          | API calls                                                                                                      | Notes                                                                                                                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/`                            | `GET /api/projects/:t/agent_applications/`                                                                     | List card. Slug, description, live revision short-sha, last-session timestamp.                                                                                          |
| `/agents/:slug`                | `GET /api/projects/:t/agent_applications/<id>/` plus the live revision's bundle manifest                       | Overview tab. Spec rendered as a Quill `Card`-per-section (model, triggers, tools, skills, secrets, limits). System prompt (`agent.md`) rendered with syntax highlight. |
| `/agents/:slug/bundle`         | `GET /api/projects/:t/agent_applications/<id>/revisions/<rev>/bundle/` (manifest) + per-file fetches on-demand | File tree on the left, content on the right. Read-only viewer; no edit affordance.                                                                                      |
| `/agents/:slug/revisions`      | `GET /api/projects/:t/agent_applications/<id>/revisions/`                                                      | Timeline view. Status badge (`draft`/`ready`/`live`/`archived`), created-by, frozen-sha, promoted-at, preview URL (per `revision-routing.md`).                          |
| `/agents/:slug/revisions/:rev` | revision detail + bundle manifest                                                                              | Same shape as overview, scoped to a specific revision. Diff against live (next col) is a stretch goal for v0.1.                                                         |
| `/agents/:slug/sessions`       | `GET /api/projects/:t/agent_applications/<id>/sessions/`                                                       | Paginated. Trigger source, principal, state, started-at, turn count, cost (via `per-turn-cost-capture.md`).                                                             |
| `/agents/:slug/sessions/:id`   | `GET /api/projects/:t/agent_applications/<id>/sessions/<sid>/` + live SSE `/listen/<sid>`                      | The big one. Conversation pane (assistant turns, tool calls expandable inline), reasoning pane (optional, per `streaming-and-reasoning.md`), trace pane (events).       |
| `/agents/:slug/logs`           | LLM analytics queries (per `self-healing-agents.md` §3.1) tagged with `$agent_application_id`                  | Aggregated view across sessions. Cost over time, error rate, tool-call distribution.                                                                                    |
| `/agents/:slug/approvals`      | `GET /api/projects/:t/agent_applications/<id>/pending_approvals/`                                              | Per `approval-gated-tools.md`. Read-only here — approve/deny goes through the chat (or via the existing MCP / Slack surface; UI is just a list view).                   |

All pages are SSR by default with React Server Components for the
shell + initial data; client-only pieces (live SSE tail, chat dock,
filters) are islands inside.

Pagination, filtering, search: standard query params, no fancy
state. The Next.js cache + RSC streaming gets us "fast enough"
without a Redux-equivalent.

## 7. Editing mode — the concierge agent

The "edit" affordance on any read page opens a chat dock pinned to
the right side. The dock is itself a chat-trigger session against a
specific deployed agent — the **agent-console concierge** — that
lives in a PostHog-owned org. Mental model:

```text
"Edit the system prompt of weekly-digest"
                │
                ▼
┌──────────────────────────────────────────────┐
│  concierge agent session                     │
│                                              │
│  principal:   the human (via OAuth-scoped    │
│               session principal, per         │
│               per-session-access-elevation)  │
│                                              │
│  spec.tools:  every agent-platform MCP tool  │
│               + a handful of `kind: "client"`│
│               tools the console fulfills     │
│               (@posthog/ui/focus, ...)       │
│                                              │
│  spec.skills: the authoring skill            │
│               (agent-authoring-flow §6)      │
└──────────────────────────────────────────────┘
                │
                │  invokes
                ▼
        agent-applications-revisions-* tools
        agent-applications-set-env tools
        agent-applications-revisions-test-run
        ...
```

Why this shape instead of a forms UI:

- **Single mental model.** Reading is a website. Editing is a
  conversation with an agent that knows how to edit. No bespoke
  React form for spec + bundle + secrets + tests + promotion.
- **Same edit surface as the MCP-driven authoring AI.** Whatever
  works for a Claude session in the MCP context works for a user
  in the console. Bugs and features in one surface auto-propagate
  to the other.
- **The concierge already exists in design.** It IS the agent
  described by [`agent-authoring-flow.md`](agent-authoring-flow.md).
  This plan just gives that agent a chat UI.

The concierge is **a regular agent on the platform** — it's not
special-cased. Anyone could clone it. PostHog ships and maintains
the canonical one; large customers might fork it (e.g. to add their
internal review-board step before promote).

### 7.1 Principal flow — the user acts as themselves

A naive read of "the concierge acts on the user's behalf" suggests
PostHog's org holds the user's OAuth token. We don't want that
(custody risk, audit confusion, blast radius).

Instead: the concierge session's `principal` IS the human user —
their PostHog user id + the OAuth scopes they granted the console at
login. The session-elevation machinery from
[`per-session-access-elevation.md`](per-session-access-elevation.md)
already supports a principal carrying a specific human identity; the
concierge's tool calls execute under that principal, meaning every
mutation (revision create, bundle update, promote) shows up in the
PostHog activity log as **the user** acting — not as "agent-console
concierge".

Mechanically: the console mints a short-lived (15min) session
principal token tied to the human's OAuth session, attaches it as
the `principal` field when opening the concierge chat session, and
the runner threads it through to every tool call. The concierge
agent's own org-of-record is PostHog's, but no PostHog credential
ever signs a tool call against a customer's data.

This composes cleanly with the auth gate from
[`draft-preview-auth.md`](draft-preview-auth.md): the user's
principal authenticates against Django's PAT-equivalent path for
draft testing too.

## 8. Client-fulfilled tools — the new platform surface

The single new platform concept this plan introduces is
**client-fulfilled tools** — tools the spec author declares,
identical in shape to native and custom tools, except their
_implementation_ lives in the chat UI's browser session rather than
on the runner.

### 8.1 Why

The concierge needs to drive the console's view, not just produce
text. "I just edited `skills/research.md`" should _load_ that file
in the read panel beside the chat dock. "I started a test run"
should _open_ that test session's live view. Without something like
this, the user has to keep manually navigating to whatever the
concierge worked on — defeating the point of the chat.

Server-side tools can't do this — the runner has no notion of
"the open browser tab". The signal has to originate from a tool
call, flow back through the existing SSE event bus to the
specific client driving the session, and execute in that client.

### 8.2 Where the contract lives — in the spec, not the client

A key design rule: **the spec is the source of truth for the
agent's tool surface, including client-fulfilled tools.** The
client cannot inject a tool that the spec didn't declare.

Three reasons this matters:

- **Authoring is local.** The agent's `agent.md` and skills can
  reference `@posthog/ui/focus` by name and expect it to exist.
  Authors write "when you start editing a file, call
  `@posthog/ui/focus`" — that reference is statically resolvable
  against the spec, the same way every other tool reference is.
- **Audit + access control.** A malicious or buggy client cannot
  surface arbitrary new tool ids to the model. Whatever the model
  can call is what the spec author approved at freeze time.
- **Validation.** Pre-freeze validation
  (`agent-applications-revisions-validate`,
  [`agent-authoring-flow.md`](agent-authoring-flow.md) phase 4)
  catches misspelled client-tool refs in the spec, the same as it
  catches misspelled native-tool refs.

Spec shape — a new `kind: "client"` joins the existing
`native` / `custom_template` / `custom` discriminator:

```jsonc
{
  "tools": [
    { "kind": "native", "id": "@posthog/query" },

    // Reference the platform's well-known UI client tool — schema
    // and description are pulled from a central registry (same
    // model as @posthog/* native tools).
    { "kind": "client", "from_native": "@posthog/ui/focus" },
    { "kind": "client", "from_native": "@posthog/ui/toast" },

    // Or declare a bespoke client tool inline — for one-off agents
    // whose UI needs aren't covered by the well-known set.
    {
      "kind": "client",
      "id": "ui/scroll_to_anchor",
      "description": "Scroll the read panel to the given anchor.",
      "args_schema": {
        /* zod-like */
      },
      "required": false,
    },
  ],
}
```

`required` semantics:

- `false` (default) — if the connecting client doesn't declare it
  can handle this tool, the runner hides it from the model's tool
  surface and the session proceeds. The agent's prompt should be
  written defensively for this case.
- `true` — refuse to open the session unless the client declares
  it can handle this tool. Useful for an agent that fundamentally
  requires a UI client (e.g. a guided walkthrough).

### 8.3 The client opt-in handshake

When the chat dock opens a session it identifies itself as a
client capable of fulfilling specific tools. Alongside the usual
`run` payload:

```jsonc
{
  "trigger": "chat",
  "principal": "...",
  "client": {
    "kind": "agent-console@1",
    "handles": ["@posthog/ui/focus", "@posthog/ui/toast"],
  },
}
```

`client.kind` is for observability (which client implementation is
talking to us — useful when a buggy client version is misbehaving
in the wild). `client.handles[]` is the list of tool ids the
client commits to fulfilling.

The runner reconciles `client.handles[]` against the spec's
`tools[]` of `kind: "client"`:

- **In spec AND handled by client** → enabled on the model surface.
- **In spec, NOT handled by client, `required: false`** → hidden
  from the model surface. Emitted once as a session-start info
  event so the UI can surface "this agent has tools your client
  can't render".
- **In spec, NOT handled by client, `required: true`** → session
  open fails with `client_tool_unsupported`, listing the missing
  tool ids so the client can prompt the user (e.g. "open this
  in the agent console to continue").
- **Handled by client, NOT in spec** → ignored. The client cannot
  add to the model surface.

### 8.4 Call dispatch

When the model calls a `kind: "client"` tool the runner does NOT
hit its local tool registry. Instead:

1. Runner emits a `client_tool_call` SSE event over `/listen`,
   addressed to the original client's connection. Carries the
   tool id, the args, and a call id.
2. Client executes the call locally — for `@posthog/ui/focus` it's
   a React navigation; for `@posthog/ui/toast` it's a Sonner
   notification.
3. Client `POST`s the result to a new ingress endpoint
   `/sessions/<id>/client_tool_result` with the call id + body.
4. Runner unblocks the model turn with the result, continues.

Runner-enforced limits:

- Args must serialize ≤ 16 KiB.
- Results must serialize ≤ 16 KiB.
- Timeout (default 30s) — if no result arrives, the runner returns
  `{ error: "client_tool_timeout" }` to the model so the turn
  doesn't hang.
- If the client's `/listen` connection disconnects mid-call, the
  call resolves to `{ error: "client_disconnected" }`. A
  reconnecting client picks up the session but does not inherit
  in-flight calls — the model has already seen the error and moved
  on.

### 8.5 Well-known client tools — `@posthog/ui/*`

The runner maintains a registered set of well-known client-tool
contracts at `@posthog/ui/*`, served the same way native tools are
(catalog endpoint, schema fetch). The `@posthog/agent-chat` package
(§11) ships handlers for each well-known id; specific consumer
apps wire those handlers up to their own navigation primitives.

Initial set:

- `@posthog/ui/focus` — see §9.
- `@posthog/ui/toast` — surface a transient status message.
- (Future) `@posthog/ui/confirm`, `@posthog/ui/prompt`, etc.

A spec author references one with `{ "kind": "client", "from_native":
"@posthog/ui/focus" }` and the description + schema + version pin
flow through automatically — no copy-paste, no schema drift.

Bespoke `id`-defined client tools stay available as the escape
hatch for one-off agents whose UI needs aren't covered.

### 8.6 Why this is general, not console-specific

This protocol applies to any chat-trigger client: a Slack message
viewer that wants to render an inline preview, a third-party MCP
host (Claude Desktop) that wants to expose UI primitives, an
embedded React SDK in a customer's product. It's a runner feature,
not a console feature. The console is the first consumer; we ship
the protocol once, and `@posthog/agent-chat` (§11) is what other
React consumers reuse.

Different client kinds will fulfill different subsets of the
well-known `@posthog/ui/*` set. A Slack viewer might handle
`@posthog/ui/toast` and `@posthog/ui/confirm` but not `ui/focus`.
That's fine — the spec lists the union of UI capabilities the
agent _can_ leverage; each client opts into the subset it
implements.

### 8.7 Security model

A client tool result is **untrusted input** to the model — same as
any other tool's stdout. Two additional guarantees follow from §8.2:

- The client cannot extend the model's tool surface. Whatever the
  model can call is exactly what the spec author approved.
- A client tool's implementation cannot mutate session state,
  alter the spec, or call other tools server-side. If the model
  wants to perform a side effect, it calls a real server-side
  tool with proper authorization. `@posthog/ui/focus` is purely
  cosmetic; the worst a malicious client can do is lie about
  what it focused on, which the model cannot verify and should
  not depend on.

## 9. The `@posthog/ui/focus` well-known tool — flagship use case

`@posthog/ui/focus` is what makes the chat dock feel responsive. It
ships as a well-known client tool (§8.5); the concierge's spec
references it with:

```jsonc
{ "kind": "client", "from_native": "@posthog/ui/focus" }
```

Canonical contract (held in the runner's well-known registry):

```jsonc
{
  "id": "@posthog/ui/focus",
  "version": "1",
  "description": "Bring a specific resource into the user's view. Call this whenever you start working on something (file, revision, session) so the user sees what you're seeing. The result tells you whether the user actually saw it; if `focused: false`, spell out what you're doing in text instead.",
  "args_schema": {
    "type": "object",
    "oneOf": [
      { "properties": { "kind": { "const": "file" }, "path": { "type": "string" } } },
      { "properties": { "kind": { "const": "revision" }, "revision_id": { "type": "string" } } },
      { "properties": { "kind": { "const": "session" }, "session_id": { "type": "string" } } },
      {
        "properties": {
          "kind": { "const": "spec_section" },
          "section": { "enum": ["triggers", "tools", "skills", "secrets", "limits"] },
        },
      },
    ],
  },
}
```

Console handler behaviour when `@posthog/ui/focus` fires:

- `kind: "file"` → navigate the bundle view to that file path.
- `kind: "revision"` → load the revision detail page.
- `kind: "session"` → open the live session viewer with the SSE
  tail already streaming.
- `kind: "spec_section"` → scroll the spec panel to that section
  and highlight briefly.

The user controls a toggle in the chat dock: **"Follow the agent"**
(default on). When off, focus events still arrive but are presented
as quiet "💡 jump to skills/research.md" inline cues in the chat
transcript rather than triggering navigation. Important for
reviewers who want to evaluate the agent's narration without their
view being yanked around.

The result the client returns to the runner is small and informative
but boring:

```jsonc
{ "focused": true, "kind": "file", "path": "skills/research.md" }
```

Or `{ "focused": false, "reason": "user_paused_follow" }` if the
user disabled follow-mode. The model uses this to know whether
the user actually saw what it referenced — a `focused: false` lets
the agent decide to spell something out in text instead.

A Slack viewer or MCP host that doesn't render file trees can
simply omit `@posthog/ui/focus` from its `client.handles[]`; the
runner hides the tool from the model's surface (per §8.3) and the
concierge's prompt — which is written defensively — falls back to
text narration. No spec change needed to support a new client kind
with a different capability subset.

## 10. The chat dock UX

A few decisions that fall out of the above:

- **One concierge session per tab.** The dock is pinned across all
  read pages; opening another agent's overview while in mid-edit
  keeps the same session. The chat is the user's edit-session, not
  the read page's.
- **Resume on reload.** Session id stored in `localStorage` keyed by
  `(team_id, agent_application_id)`. Closing and reopening the tab
  picks up where the user left off, including streaming an
  in-progress turn from the `/listen` SSE.
- **One chat per agent.** Switching the read panel to a different
  agent prompts "open the concierge for `<new-slug>`?" — separate
  edit-sessions per agent so chat history stays on-topic.
- **Approval inline.** When `approval-gated-tools.md` wants a human
  approval, the runner already surfaces it via the SSE bus. The
  dock renders it inline as an Approve / Deny button row — composes
  with the existing approval surface, doesn't replace it.

All of these behaviours live inside `@posthog/agent-chat` (§11),
not in the console. The console only wires the navigation handler
for `@posthog/ui/focus` and the OAuth-derived `principalToken`.

## 11. Packaging — `@posthog/agent-chat`

The chat dock is genuinely reusable. It's the only piece of the
console that:

- Speaks the runner's session protocol (open + listen + send +
  cancel) over HTTP + SSE.
- Implements the client-fulfilled tool handshake (§8.3) —
  declaring `client.handles[]`, receiving `client_tool_call`
  events, dispatching to registered handlers, posting results
  back.
- Renders streaming assistant turns + tool-call inspectors + the
  per-session cost / approval inline cards.

Everything else (read surfaces, OAuth, region picker) is
console-specific. Pulling the chat into its own package means:

- A future "embed the concierge in the main PostHog frontend" can
  drop `<AgentChat />` in next to an insight or a feature flag —
  same dock, same UX, no fork.
- Customers building React SDKs on top of the agent platform get a
  drop-in chat surface. The platform's "we are the runtime, not
  the UI" stance stays clean; this package is the canonical
  reference UI.
- The chat can be Storybook'd in isolation — useful both for
  design iteration and for `services/agent-tests/` integration
  where we want to drive client-tool handlers without spinning up
  Next.js.

### 11.1 Package shape

Lives at `packages/agent-chat/` as a sibling to
[`packages/quill/`](../../../packages/quill). Same monorepo
conventions:

| Concern        | Choice                                                                                                                       |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Published name | `@posthog/agent-chat`. Start unpublished; flip to npm once the API stabilizes — same trajectory as Quill.                    |
| Dependencies   | `@posthog/quill` (UI), React 18+ peer. No Next.js, no PostHog-specific auth, no Django coupling.                             |
| Types          | Re-exports the client-relevant subset of `@posthog/agent-shared` (session shapes, event kinds, well-known tool contracts).   |
| Styling        | Tailwind v4 via Quill's `tokens.css`. Consumer wires Tailwind same way as Quill — `agent-chat` ships a `@source` glob too.   |
| Storybook      | Inside `packages/agent-chat/storybook/`. Stubs the ingress connection with a fake SSE feed so stories run fully client-side. |
| Workspace      | Internal `packages/agent-chat/packages/*` split same as Quill if it grows (e.g. `chat-protocol` vs `chat-ui`); start as one. |

### 11.2 API surface (sketch)

```tsx
import {
  AgentChat,
  type ClientToolHandler,
} from '@posthog/agent-chat'

const focusHandler: ClientToolHandler<'@posthog/ui/focus'> = {
  id: '@posthog/ui/focus',
  handle: async (args) => {
    router.push(buildUrl(args))
    return { focused: true, kind: args.kind }
  },
}

<AgentChat
  ingressUrl="https://ingress.agents.posthog.com"
  applicationSlug="weekly-digest"
  principalToken={token}
  clientKind="agent-console@1"
  handlers={[focusHandler, toastHandler]}
  followingEnabled={following}
  onFollowingChange={setFollowing}
/>
```

The `<AgentChat />` component owns: opening + resuming sessions,
streaming UI, tool-call rendering, handler dispatch, error
recovery, the "Follow the agent" toggle. The consumer owns:
where to mount it, which handlers to provide, auth.

`ClientToolHandler<T>` is generic over the well-known tool id, so
TypeScript infers args/result shapes from the well-known registry
exported by `@posthog/agent-shared` — same model as Quill's typed
primitive props.

### 11.3 What's NOT in this package

- **OAuth / session-principal minting.** That's the consumer's
  problem — the console gets `principalToken` from PostHog OAuth;
  an embedded in-frontend dock gets it from the Django session; a
  customer SDK gets it however they wire their own auth. The
  package only ever receives the token.
- **Specific client-tool handlers.** The `@posthog/ui/*` contracts
  are exported (so handler signatures type-check) but their
  _implementations_ are app-specific. The console provides
  navigation for `@posthog/ui/focus`; a Slack viewer wouldn't.
- **Read surfaces.** No bundle viewer, no revision timeline. Those
  stay in `services/agent-console/` — they're the read website,
  not the chat.

### 11.4 Consumption in the console

`services/agent-console/` adds `@posthog/agent-chat` to its
workspace deps, imports `<AgentChat />` into a dock component, and
provides the `@posthog/ui/*` handlers locally. The console-specific
shell (routing into the read panel from `ui/focus`) is a thin
adapter over the Next.js router primitives the console already
uses.

### 11.5 Future consumers — why this lift is worth it now

The package shape is cheap if we draw the boundary at v0 — the
chat is being written from scratch anyway. The boundary is
expensive to introduce later (every coupled detail has to be
unwound). Worth it on day one because:

- **PostHog frontend native dock.** When `app.posthog.com` decides
  it wants an agent dock alongside insights / feature flags /
  surveys, it's `pnpm add @posthog/agent-chat` + provide handlers,
  not a fork.
- **Customer React SDK.** A `@posthog/agent-sdk-react` package
  could re-export `<AgentChat />` plus a customer-facing
  principal-mint helper, becoming the supported embed surface
  for end users.
- **Agent tests.** `services/agent-tests/` can drive client-tool
  handlers programmatically — register a fake `ui/focus` handler
  in the test harness, assert it was called with the right args,
  no headless browser needed.
- **Storybook + design iteration.** Quill stories already prove
  this is the right rhythm. The chat is the second-most-complex
  surface in the platform; iterating it in Storybook is far
  faster than driving the whole console.

## 12. Local-dev shape

```bash
# In services/agent-console/
pnpm dev                          # Next.js on :3040
```

Wired against the same local stack the rest of the platform uses
(per `docs/agent-platform/docs/local-dev.md`). The console talks to
local Django on `:8010` for OAuth + REST, local ingress on `:3030`
for chat + SSE.

For OAuth in local dev: ship a `dev-bypass` mode that mints a fake
session principal from a local config file, identical in shape to
what the real OAuth flow produces. No need to run `oauth.posthog.com`
locally. Gate strictly on `NODE_ENV !== 'production'` + a typed
config flag so prod can never accidentally start in bypass mode.

`@posthog/agent-chat` runs its own Storybook (`pnpm --filter
@posthog/agent-chat storybook`) independently of the console for
iterating on the chat surface in isolation.

## 13. Deployment

**v0 — Dockerized service in the repo.** `services/agent-console/`
gets a Dockerfile, builds the same way the other agent-platform
services do. Deploys live next to ingress / runner / janitor —
specifically to `console.agents.posthog.com` via the same wildcard
cert (per [`revision-routing.md`](revision-routing.md)).

**v1 — Vercel option.** Next.js apps deploy cleanly to Vercel; if we
decide the console is better served from Vercel's edge (faster
geographic distribution, no need to run Node ourselves), the
Dockerfile becomes optional. The OAuth flow already works on any
HTTPS origin we add to the OAuth client allowlist.

**v2 — Self-host story.** OSS customers running the agent platform
get a `docker-compose` snippet that wires the console alongside
the ingress / runner / janitor stack. PostHog OAuth becomes
"point at your own PostHog instance"; works because the OAuth
proxy already supports multi-region / self-hosted via the existing
`oauth-proxy` design.

## 14. What this is _not_

- **Not a replacement for the in-PostHog frontend.** If `app.posthog.com`
  decides to host an "Agents" tab natively later, the read pages
  can be ported as kea logics and the chat drops in directly via
  `@posthog/agent-chat`. No fork.
- **Not the place to add agent platform features.** All capability
  goes through specs, runner, ingress. The console is a viewer +
  edit-via-chat affordance; it doesn't add product behaviour.
- **Not a generic agent-marketplace surface.** Customer agents only.
  No cross-team discovery, no public listings. If we want a
  marketplace later it's a different surface.

## 15. Open questions

1. **How does the concierge agent get installed?** PostHog's org
   needs the agent provisioned in every region. The simplest shape
   is to ship its bundle alongside the platform code and have a
   janitor bootstrap step ensure it exists at startup. Composes
   with [`skill-templates.md`](skill-templates.md) — the concierge
   is effectively a "template agent" auto-provisioned per region.
2. **Per-region console deploys vs single global console.** Single
   console with region picker is simpler for users but introduces
   cross-region API calls. Per-region (`console-us.agents.posthog.com`,
   `console-eu.agents.posthog.com`) mirrors how the rest of the
   platform splits. Lean toward per-region; revisit if cross-region
   sign-in confusion becomes a real pain.
3. **Session principal token shape.** The "short-lived OAuth-scoped
   principal token" mentioned in §7.1 needs concrete plumbing. The
   simplest path is to extend the existing `SessionPrincipal` shape
   (per `per-session-access-elevation.md`) with an
   `oauth_token_ref` field that points at a server-side row holding
   the actual token, fetched on tool dispatch. No tokens in
   plaintext message contexts.
4. **Multi-tab editing.** If the user opens the console in two tabs,
   both with the same agent open, do they share the concierge
   session? Default: yes (resume by session id from `localStorage`).
   Stretch: cross-tab BroadcastChannel to mirror chat state. Skip
   for v0.
5. **Mobile.** The chat dock + file panel layout is desktop-shaped.
   v0 ships desktop-only; mobile is a "view a single session on the
   go" use case that a stripped-down responsive layout could cover
   later.
6. **Test harness for client tools.** The runner's existing harness
   in `services/agent-tests/` doesn't drive a browser. With the
   package split (§11) the cleanest answer is: import
   `@posthog/agent-chat`'s handler-dispatch module directly into
   the harness, register fake handlers, assert calls. No Next.js,
   no headless browser, no fake SSE plumbing — the harness becomes
   a normal node test that exercises the same code as the console.
7. **Concierge cost attribution.** Concierge sessions burn model
   tokens against the user's team (the principal is the user). Make
   this visible in the dock — "this edit session has cost $0.04 so
   far" — so users aren't surprised. Composes with
   [`per-turn-cost-capture.md`](per-turn-cost-capture.md).
8. **Read-mostly really means read-mostly.** What about deleting an
   archived revision, or rotating a secret? These don't fit "edit
   via concierge" cleanly — they're one-off admin actions. v0
   answer: do them through the concierge too ("delete revision X"),
   even if it's heavyweight for a one-click action. Revisit if
   users actually push back.
9. **Should `@posthog/agent-chat` ship default `@posthog/ui/*`
   handlers?** Argument for: every consumer rewrites the same
   `ui/toast` Sonner glue. Argument against: handlers necessarily
   touch app-specific navigation / notification primitives, so a
   default may be a footgun. Lean toward shipping a
   `defaultHandlers` export that consumers can take or replace
   per-id — opt-in convenience without forcing a coupling.

## 16. Rollout

**v0 — read-only console + concierge edit.**

- New package: `packages/agent-chat/` — `<AgentChat />`, handler
  API, SSE plumbing, Storybook. Unpublished; consumed via
  workspace link.
- Next.js app under `services/agent-console/`, deployed to
  `console.agents.posthog.com`.
- OAuth login via `oauth-proxy`; scoped read access.
- Read surfaces for: agent list, agent overview, bundle viewer,
  revisions, sessions (incl. live SSE tail).
- `<AgentChat />` embedded as the dock; one concierge session per
  (team, agent).
- Client-fulfilled tool protocol shipped on the runner;
  well-known `@posthog/ui/focus` and `@posthog/ui/toast` handlers
  shipped by the console.
- Local-dev wiring + `dev-bypass` OAuth mode.

**v1 — review + diff polish.**

- Revision diff view (live ↔ draft).
- Approvals dock (inline approve/deny from the chat).
- Logs page hooked into LLM analytics.
- Cost rollups.
- `@posthog/agent-chat` publishes to npm once API stabilizes.

**v2 — fleet view + native embed.**

- Cross-agent dashboard hinted at in
  [`_ROADMAP.md`](_ROADMAP.md) §"What's not in scope".
- Multi-region console (or per-region rollout, per Q2).
- Self-host packaging (Q14).
- `<AgentChat />` embedded inside `app.posthog.com` as a native
  dock — first non-console consumer of the package, proves the
  abstraction.

## 17. Dependencies + what this enables

**Hard depends on:**

- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  — the session-principal model carries the human's identity through
  the concierge's tool calls (§7.1).
- [`streaming-and-reasoning.md`](streaming-and-reasoning.md) — the
  chat package + the session viewer both consume the same SSE
  event shapes.

**Composes with:**

- [`agent-authoring-flow.md`](agent-authoring-flow.md) — the
  concierge agent IS the authoring AI described there, given a chat
  UI. The authoring skill is what the concierge loads on every
  session start.
- [`draft-preview-auth.md`](draft-preview-auth.md) — when the
  concierge invokes a draft for testing, the call routes through the
  Django proxy with the user's principal.
- [`revision-routing.md`](revision-routing.md) — the console's
  revision detail page renders the preview URL (`<prefix>.<slug>.agents.posthog.com`)
  as a shareable link for human reviewers.
- [`approval-gated-tools.md`](approval-gated-tools.md) — pending
  approvals surface in both the dedicated `/agents/<slug>/approvals`
  page and as inline cards in the chat dock.
- [`per-turn-cost-capture.md`](per-turn-cost-capture.md) — the
  cost-per-session field on `agent_session` drives the cost rollup
  on the sessions list and the concierge's running cost indicator.
- [`typed-config-loader.md`](typed-config-loader.md) — the console
  service uses the same typed-env pattern as the rest of the
  platform.

**What this unblocks:**

- A real audience for the platform beyond MCP-fluent developers.
  Reviewers, ops engineers, and authors all get a surface.
- The client-fulfilled tool protocol generalizes: future surfaces
  (Slack Block Kit cards, embedded SDK widgets, Claude Desktop
  MCP UI) declare `client.handles[]` for the well-known
  `@posthog/ui/*` set they support; spec authors don't have to
  re-author per client kind.
- `@posthog/agent-chat` as a clean embed surface for any future
  context that wants to talk to a deployed agent — main PostHog
  frontend dock, customer React SDKs, internal tooling.
- A natural place to render the activity log
  ([`per-session-access-elevation.md`](per-session-access-elevation.md)
  §8) and the LLM analytics
  ([`self-healing-agents.md`](self-healing-agents.md) §3.1) when
  those land.
- "Show me what changed between this draft and live" — diffs and
  visual review — which is what we'd want before a human reviewer
  promotes a self-healing-agent's candidate draft.
