# Design — session state machine + restart

**Status:** shipped (v0). **Owner:** ben.

This is the contract the platform now operates under for session lifecycle.
Replaces the older `queued / running / waiting / completed / failed` state
machine with a smaller one that's clearer about "the agent's turn is over,
the user can still talk to it" vs "the agent's job is irreversibly done."

## 1. State machine

Five states, two terminal:

```text
queued    — awaiting a worker claim.
running   — claimed; worker actively driving the turn.
completed — the agent finished its turn. Session is OPEN — /send re-queues.
            Default end-of-turn state (natural stop, meta-end-turn,
            meta-ask-for-input).
closed    — TERMINAL. Reached via @posthog/meta-end-session.
            /send returns 410 unless the trigger config sets `allow_restart`.
failed    — TERMINAL. Reached via model error, max_turns, max_tokens, an
            unhandled exception, or /cancel. /send returns 410 regardless
            of `allow_restart` — restarting would likely just re-fail.
```

`waiting` is gone. It used to mean "parked on `meta-ask-for-input` — a user
reply is expected." Now `meta-ask-for-input` is a UI focus hint that ends
the turn at `completed` like any other turn end (see §3).

## 2. `/send` policy

Across all triggers that expose `/send`-shaped continuations (`chat`,
`mcp.tools/call ask`):

| Existing state | `/send` outcome                                                                                                         |
| -------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `queued`       | 200 — appended to `pending_inputs`. Runner drains on claim.                                                             |
| `running`      | 200 — same. Runner drains on the next turn.                                                                             |
| `completed`    | **200 — re-queues the session.** Appends to `pending_inputs`, flips state to `queued`. Runner picks up.                 |
| `closed`       | 200 if `allow_restart` is set on the trigger config (re-queues like `completed`); **410 `session_terminal` otherwise**. |
| `failed`       | 410 `session_terminal`. Always.                                                                                         |

The Slack trigger uses `external_key`-driven continuation instead of
`/send`; the same terminal/open distinction applies — `completed`
sessions in a thread are resumed on the next mention, `closed` / `failed`
ones spawn a fresh session.

## 3. Meta tools

Three always-on meta tools the runner intercepts. The system prompt
should teach the model which to reach for and when — see
[`framework-system-prompt.md`](framework-system-prompt.md) §3.1.

### `@posthog/meta-end-turn`

Explicit "I'm done with this turn." Session lands at `completed` (open).
Functionally equivalent to natural `stopReason: 'stop'` — both end the
turn without closing the session.

**Why have it at all?** It pairs explicitly with `meta-end-session` in
the system prompt: "use `end-turn` when you're done responding for now;
only reach for `end-session` if the agent's task is irreversibly
finished." Forces the model to think about whether the session should
remain available.

### `@posthog/meta-ask-for-input`

UI focus hint: "the user-facing client should surface a prompt asking
the user a specific question, and treat the next user message as the
answer." Functionally equivalent to `end-turn` from a state-machine
perspective — the session lands at `completed` (open).

The runner emits an `ask_for_input` bus event (carries
`data.prompt`) so a Slack thread / chat dock / web UI can render a
focus affordance ("Type your answer to: …"). No state-machine impact.

### `@posthog/meta-end-session`

Hard close. Session lands at `closed` (terminal unless the trigger
sets `allow_restart`). Authors instruct the model in `agent.md` when
to reach for this — e.g., a one-shot agent that has delivered its
deliverable and there's nothing else to do.

## 4. `allow_restart`

New config on the chat + mcp trigger configs:

```jsonc
{
  "triggers": [
    {
      "type": "chat",
      "config": {
        "require_auth": false,
        "allow_restart": true, // default false
      },
    },
    {
      "type": "mcp",
      "config": {
        "allow_restart": true, // default false
      },
    },
  ],
}
```

When true, `/send` to a `closed` session reopens it (state → `queued`,
message appended to `pending_inputs`) instead of returning 410. Has no
effect on `failed` sessions.

Slack triggers don't carry the flag — Slack continuation is `external_key`-
driven, so an author who wants a closed thread to be reopenable should
either (a) avoid calling `meta-end-session` in the first place (let it
sit at `completed` indefinitely), or (b) wait for the future
`@posthog/meta-reopen` tool surface, not in v0.

## 5. Bus events

Lifecycle events the runner publishes through `SessionEventBus`:

```text
session_started, turn_started,
assistant_text, assistant_text_delta, assistant_thinking_delta,
tool_call, tool_call_start, tool_call_args_delta, tool_result,
ask_for_input  ← NEW: UI focus hint, carries `data.prompt`. Fires alongside
                 `completed` when meta-ask-for-input was called.
completed      ← Default end-of-turn event. Session is OPEN.
closed         ← NEW: hard close. Session is TERMINAL.
failed
```

`waiting` is gone. SSE consumers that previously listened for
`waiting` to render a focus UI should listen for `ask_for_input`;
consumers that treated `completed` as "stream done, drop connection"
should now treat `closed` (or `failed`) as the terminal signal.

## 6. Janitor sweep

The old "stuck waiting → failed" policy is replaced by:

- **Idle `completed` → `closed`**: sessions that have been `completed`
  (open) for longer than `idleCompletedThresholdMs` (default 24h) are
  auto-closed by the janitor sweep. Prevents long-idle sessions from
  sitting around forever. The `closed` terminal state is the right
  destination (rather than `failed`) because the agent's turn ended
  cleanly — the user just never came back.

The stuck-running re-queue + poison-pill policies are unchanged.

## 7. Rollout

Shipped in one branch. Backwards-compat notes:

- **Existing agents that ended via `stopReason='stop'`** now land at
  `completed` (open) instead of `completed` (terminal). The semantic
  change: `/send` is allowed where it previously 410'd. Authors who
  want the old hard-close behaviour should add `meta-end-session` to
  the agent prompt.
- **Existing agents using `meta-ask-for-input`** no longer park at
  `waiting`. The session lands at `completed` and the prompt comes
  out on the `ask_for_input` bus event. The next `/send` works
  identically — the user-visible flow is unchanged.
- **Existing observers/SSE consumers** looking for `waiting` won't
  see it; for `completed` they'll see it both for end-of-turn AND
  for "session done forever" (the second meaning is now `closed`).
  Bus event names should be re-pointed accordingly.

## 8. Composes with

- `approval-gated-tools.md` — approval-gated tools still synthesise
  `tool_result` and user messages into the session, no state-machine
  interaction. A session that's parked on an approval lands at
  `completed` (open); after the approval the runner picks it back up.
- [`framework-system-prompt.md`](framework-system-prompt.md) — the new
  meta tools need explicit guidance about when to use each; that plan
  owns the preamble.
- `long-running-sessions.md` — the `idleCompletedThresholdMs` sweep
  could be tuned per agent so long-running ops agents stay open longer
  than chat-style agents.

## 9. Open questions

- **`meta-reopen`** for explicit reopen from inside an agent? Useful
  if an agent wants to undo its own `meta-end-session`. Probably
  scoped to a future plan if anyone asks.
- **`/close` endpoint** for caller-initiated close (UI button, Slack
  👋 reaction)? Symmetric with `allow_restart`. Punted.
- **Janitor TTL configurability per agent**: a long-running data
  pipeline agent and a casual Q&A bot probably want different
  `idleCompletedThresholdMs`. v0 is global; v1 reads from spec.
