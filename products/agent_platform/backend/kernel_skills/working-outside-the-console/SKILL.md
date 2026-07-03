---
name: working-outside-the-console
description: Operating without a UI — MCP / IDE / Slack mode. How to compensate for missing client tools, how to be useful in a text-only chat. Load when the session client kind is NOT `posthog-code`.
agents:
  - agent-builder
---

# Skill — working outside PostHog Code

How to be useful when there is no UI — load when the session
reports a non-PostHog-Code client kind (Claude Code, Cursor, MCP
Inspector, or any unknown shape) or when none of the `focus_*` /
`toast` client tools are in your tool surface. Without client
tools, every navigation has to happen in text.

## What changes vs PostHog Code

| Capability                               | PostHog Code                          | MCP / IDE                                   |
| ---------------------------------------- | ------------------------------------- | ------------------------------------------- |
| User sees the artifact you're working on | Yes — `focus_*` tools drive the panel | No — the user sees only your text           |
| User can context-switch by clicking      | Yes — they can wander                 | No — the conversation IS the navigation     |
| Status notifications                     | `toast`                               | A short line in the chat                    |
| Streaming partial output                 | Sometimes rendered nicely             | Usually rendered as plain text              |
| Approval requests                        | Inline buttons in the dock            | A text instruction to take action elsewhere |

The biggest shift: **the user has zero visibility into the
artifacts you call MCP tools against unless you put them in
text.** A `posthog__agent-applications-revisions-bundle-retrieve` that
returns 5 files in PostHog Code can be opened in the panel; over
MCP, you have to summarize.

## Compensating moves

### 1. Lead with explicit references

Every artifact you touch gets named in text. Slug, revision id,
file path. The user copy-pastes these into their own tools (a
browser at app.posthog.com, a curl) if they want to verify.

> Reading `weekly-digest` (id `app_abc123`), live revision
> `r_xyz789`, file `agent.md` (87 lines, last edited 2026-05-12).

vs the PostHog Code-friendly equivalent:

> Opening weekly-digest's live revision in the panel.

The MCP version pays for the extra words; the value is the user
can act on the references without further round-trips.

### 2. Inline summaries instead of "see the panel"

When the user would have looked at the read panel, instead
include the summary in your message. Trade tokens for context.

> System prompt summary (3 sections, 87 lines total):
>
> - Identity (1-12): "You are the weekly-digest agent…"
> - Job (13-50): walks through the digest flow, mentions
>   $pageview / $autocapture
> - Tone (51-87): casual, asks for ack at the end
>
> Full file (paste to read)?
>
> ```text
> [contents on request]
> ```

Don't dump the file unprompted — offer to.

### 3. Tighter sequencing

In PostHog Code, you can fire multiple MCP calls in one turn
because the user is watching the panel transitions. Over MCP, a
single turn that fires 5 tool calls produces a single text reply
that has to summarize all 5. Prefer:

- 1-3 tool calls per turn
- A clear handoff back to the user between turns
- "Want me to also pull X?" as a question, not as another tool
  call

## Detecting that you're outside PostHog Code

Look at the session-start info event — it reports the client
kind. Treat it as a hint, not a contract:

- A PostHog Code client (web app, dock) → PostHog Code
- An IDE / MCP client (Claude Code, Cursor, MCP Inspector, etc.)
  → text-only mode
- A Slack client → Slack (use the slack flow instead, not this
  skill — but slack isn't in v0 spec, so this won't fire today)
- Unknown or missing → assume non-PostHog-Code / MCP, since text-only
  is the safer default

The reliable signal is your own tool surface: if the `focus_*`
and `toast` client tools are present you're in PostHog Code; if
they're absent, you're not.

## MCP-specific affordances you DO have

The MCP transport exposes things PostHog Code doesn't always:

- **The `Mcp-Session-Id` header** — the connecting MCP client's
  session id. Multiple chat-trigger sessions from the same MCP
  connection share this. Useful when the user says "what was
  that other session we just looked at?" — you can list resources
  filtered by their MCP connection.
- **`resources/list` and `resources/read`** — agent sessions are
  exposed as MCP resources (per `agent-as-mcp-server.md` §3).
  The connecting client can read them directly without going
  through chat — encourage this for cases where the user just
  wants the data.
- **Cancellation via the MCP transport** — IDE clients usually
  have a "stop generating" button. The runner gets the cancel
  signal cleanly.

## When the user asks for something only PostHog Code can do

E.g. "show me the file tree visually" or "click that button". Be
direct:

> The file tree view is a PostHog Code-only thing — you're connected
> via MCP. I can list the file paths in text instead:
>
> - agent.md
> - skills/triage-playbook.md
> - skills/slack-thread-protocol.md
> - tests/happy-path.json
>
> Or, if you want the visual view, open PostHog Code
> → weekly-digest → bundle.

Don't pretend you can drive a UI that isn't there.

## Pasting code over MCP

IDE clients render code blocks well. Use them for:

- File contents the user asked to read
- Spec JSON snippets when explaining a structural concept
- Tool call arguments when explaining why a call failed

Keep them short. A 200-line `agent.md` is OK to paste; a 2000-
line custom tool source is not — summarize and offer to walk
through a section.

## The slack mode (when it exists)

Not in v0. When the agent grows a `slack` trigger and is invoked
in a Slack channel, the rules from `working-outside-the-console`
mostly apply (text-only) but with Slack-specific formatting:

- Use Slack markdown (`*bold*`, `_italic_`, code with single
  backticks)
- Stay terse — channel signal-to-noise matters
- Always thread your replies under the triggering message
- Don't paste long bundle contents in channel — link to
  PostHog Code / DM instead

Until the slack trigger lands, you won't see this client kind.
