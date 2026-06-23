# `agent-approval-demo` — the smallest agent that demonstrates the approval gate

The goal: have a real, deployable agent that lights up the approvals UI
end-to-end the moment you chat with it.

The agent is small on purpose:

- One chat trigger (no auth — easy to drive locally).
- Three native tools, only `@posthog/memory-write` is
  `requires_approval: true`.
- Approval `type` is `agent` (the agent's owners / team admins decide
  in the console), `allow_edit: true` so the console drawer surfaces the
  JSON editor.
- One skill explaining the gate to the model.

## What it demonstrates

1. **Synthetic queued result.** Ask the agent to save a note. It
   proposes `memory-write` → the dispatcher intercepts → the model
   receives `{approval: {state: "queued", approval_url}}` instead of a
   real result.
2. **Session stays live.** No parking, no `awaiting_*` state — the
   agent continues talking to the user, shares the approval URL, ends
   its turn.
3. **Inbox + per-agent tab.** The pending row shows up at
   `/approvals` (fleet) and `/agents/agent-approval-demo/approvals`
   (per-agent).
4. **Decide path.**
   - **Approve:** the runner picks up the wake marker, dispatches
     `memory-write` for real, finalises the row, and sends the model
     a synthetic `approved + result` user message. The model
     confirms to the user. The memory file is in S3 / SeaweedFS.
   - **Approve with edits:** drawer JSON editor → submit → runner
     dispatches with the edited args.
   - **Reject:** runner sends `rejected + reason` user message; model
     surfaces to the user.

## Deploying locally

After `hogli start`:

```bash
PAT=phx_... POSTHOG_API=http://localhost:8010 PROJECT_ID=1 \
    python services/agent-tests/src/examples/agent-approval-demo/scripts/seed.py
```

The seed script is idempotent — re-running either no-ops (bundle +
spec match) or branches a new draft and re-promotes.

You can also point Claude at this directory via the MCP — the spec is
real, the bundle files are real, and they'll round-trip through the
authoring API the same way the Agent Builder fixture does.

## Driving the demo

1. Open PostHog Code and go to the agents view (the agent console now
   lives in the PostHog Code app).
2. Open the playground for `agent-approval-demo`.
3. Send: `save this note: hello world`.
4. The agent should propose `memory-write` → the dispatcher gates →
   the agent tells you the save is queued and gives you the approval
   deep link.
5. Open the approvals inbox. The pending row is there.
6. Click → drawer opens. Approve, approve with edits, or reject.
7. The agent's session refreshes with the outcome.

## What's regression-checked

[`../../cases/example-agent-approval-demo.test.ts`](../../cases/example-agent-approval-demo.test.ts)
loads this bundle from disk, deploys it through the harness, fires a
chat session, walks the full queue → approve → dispatch → wake loop,
and asserts the memory write actually landed in the bundle's S3
prefix.

If the spec / skill paths / agent.md drift in a way that breaks the
real loop, that case fails first.
