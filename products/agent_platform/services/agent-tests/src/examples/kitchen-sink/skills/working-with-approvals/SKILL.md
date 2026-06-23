---
description: How to behave around approval-gated tools — the synthetic queued envelope, the two authorities (principal = whoever drove the session; agent = a team admin), what to TELL the user while a call is parked, and how to react when an approval lands as a follow-up message. Load the moment you call a gated tool or the user asks why something is 'pending'.
---

# Working with approvals

Several of your tools are **approval-gated** (the ⛔ ones:
`memory-write`, `memory-update`, `memory-delete`, `table-delete`,
`table-truncate`, `http-request`, and a couple of `posthog__*` MCP
tools). The platform preamble above your prompt already gave you the
mechanical contract; this skill is the _bedside manner_.

## The contract, restated

1. You call the gated tool as normal.
2. The dispatcher **intercepts** it before it touches the real tool.
3. You get back a synthetic `tool_result`:
   `{approval: {state: "queued", request_id, approval_url}}`. **The
   action has NOT happened.**
4. The session does **not** park (except for `interactive` client tools
   like `set_secret`, which do). You can keep talking, call other tools,
   share the URL.
5. When a human decides, you receive a follow-up `user` message:
   `{approval: {state: "approved"}, result: <real output>}` or
   `{approval: {state: "rejected", reason}}`.

## The two authorities — know who you're waiting on

| `type`      | Who decides                                                                                                              | Where                                                       |
| ----------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| `principal` | Whoever drove this session (the asker — Slack user, chat user, etc.). An identity match, not a PostHog-permission check. | A Slack button / the console approval card / a client tool. |
| `agent`     | A **team admin** on the agent's owning team.                                                                             | The authenticated console / approvals inbox only.           |

This matters for what you tell the user:

- **`principal`** (e.g. `memory-delete`, `table-delete`, `http-request`,
  the MCP flag tools): the _asker themselves_ approves. So: "One tap to
  confirm and I'll run it — {approval_url}." It's fast; they're the
  gatekeeper.
- **`agent`** (e.g. `memory-write`, `memory-update`, `table-truncate`):
  a **team admin** has to sign off, and that might not be the person
  you're talking to. So: "I've queued that — it needs a team admin to
  approve before it saves. Here's the link: {approval_url}." Set the
  expectation that it may not be instant.

If you're not sure which gate a tool carries, you can tell from the
envelope's `approval.type` when it comes back. When in doubt, describe
it as "needs approval" and hand over the link.

## What to do — the loop

**On proposing a gated call:**

1. Acknowledge in one line ("Sure — saving that…").
2. Make the call with sensible args.
3. When the `queued` envelope returns, **tell the user it's pending and
   give them the `approval_url`.** Keep it to a line.
4. **End your turn.** Do not re-call the tool. Do not loop. Do not
   pretend it ran.

**When the approval lands as a follow-up message:**

- `approved`: confirm it happened. Surface `result` if it carries
  anything useful (often it doesn't, for a write).
- `rejected`: tell the user the approver declined, surface `reason` if
  present, and offer to revise the proposal. Don't silently retry.

## `allow_edit`

Some gates (`memory-write`, `memory-update`, `http-request`) have
`allow_edit: true` — the approver can tweak your proposed args before
running. So write your proposal as your _best_ version, but don't be
surprised if the `result` reflects an edited call. Mention it if it
diverges from what you proposed.

## Hard rules

- Never try to bypass a gate or re-emit the same args twice in one turn.
- Never claim a queued action is done.
- You cannot approve your own `agent`-type calls. You queue and wait.
- The asker being the one who _asked_ is **not** consent to the specific
  call you emitted — that's the whole reason the gate exists. Respect it.
