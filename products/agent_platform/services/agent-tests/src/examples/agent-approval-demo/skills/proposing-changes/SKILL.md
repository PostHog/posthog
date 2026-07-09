# Proposing changes through an approval gate

Some tool calls — including this agent's `memory-write` — are
**approval-gated**. Use this skill to react predictably when the
dispatcher returns a `queued` envelope instead of the real result.

## Recognising the envelope

When a gated tool call queues, the synthetic `tool_result` looks like:

```jsonc
{
  "approval": {
    "request_id": "ar_abc123",
    "state": "queued",
    "approver_hint": "an authorized admin on this team",
    "approval_url": "https://app.posthog.com/agents/<slug>/approvals/ar_abc123",
  },
}
```

Two signals tell you it's not the real result:

- `approval` key is present.
- `state` is exactly `"queued"`.

If the prior request was rejected, the envelope also carries
`prior_decision: { state, reason }` — surface that to the user so they
know why you're asking again.

## What to say to the user

One short line. Examples:

> Queued the save — your approver can confirm at
> https://app.posthog.com/agents/approval-demo/approvals/ar_abc123.
> I'll let you know when it lands.

Don't paste the full JSON envelope. Don't speculate about who'll
approve it — the `approver_hint` is descriptive only.

## What NOT to do

- Don't immediately re-propose the same call. The platform's
  idempotency rule will return the same queued row, but it confuses
  the user.
- Don't pretend the write happened. The model is the one that has to
  carry that contract — if you say "saved" before the approval lands,
  you've lied to the user.
- Don't park your turn waiting for the approval. The session is still
  live; finish your turn and let the wake message resume the
  conversation later.

## When the approval lands

A `user` message arrives in a later turn carrying the real outcome.
Read the `state`:

- `approved` — the tool dispatched. `result` carries whatever the real
  tool returned (for `memory-write`, typically a small confirmation
  shape). Acknowledge briefly.
- `rejected` — the approver said no. `reason` is often present.
  Surface it and ask if the user wants to revise.
- `expired` — TTL elapsed without a decision. Ask if they still want
  to do it; if so, re-propose (the dispatcher creates a fresh row).
- `approved` + `dispatch_failed` — the human approved but the tool
  threw downstream. Surface the error from `error` and decide if it's
  retryable.
