# PostHog AI recovery checks

The [AI browser suite](../../products/posthog_ai/frontend/e2e/architecture.md) covers chat submission during workflow
registration, queued worker startup, and approval delivery for Claude and Codex. It runs real services with reusable
synthetic provider responses. See its architecture guide for local and CI commands, evidence, and troubleshooting.

Python orchestration and replay unit tests live in `products/posthog_ai/eval_harness/test/e2e/`.
Browser specs, provider fixtures, and artifacts remain in `products/posthog_ai/frontend/e2e/`; the existing CLI entrypoints forward to the harness.
CI prints full Flox activation logs when dependency preparation fails before the browser suite starts.

The browser handles two explicit startup rejections:

- Task creation and resume return `503 warm_run_activation_unavailable` with a signed retry token when Temporal confirms nondelivery.
  The browser retries the identical payload for up to 20 seconds, including the first request, and reuses the first token to pin the original run, workflow, and message.
- Approval delivery returns `503 agent_session_not_ready` for the exact upstream HTTP 400 no-active-session rejection.
  The browser retries for up to ten seconds and requires confirmed approval resolution.

Submission exhaustion preserves the draft, attachments, and unsent context for manual retry.
Approval submission immediately reveals the composer; failed delivery restores the approval with its answers, feedback, and selections.
An ended approval target returns `409 permission_target_ended` and clears the stale card.
Cancellation or replacement of the owning run or approval stops retries.

Transport errors, unrelated 503 responses, and JSON-RPC errors inside HTTP 200 do not qualify for automatic readiness retries.
An ambiguous transport failure could follow successful execution; replaying it could execute a tool twice.

## Coverage and remaining flows

The startup and approvals layer adds these five regression flows:

1. Cold creation and an idle follow-up keep the same task/run, model, and permission mode. Attached event context reaches the first submission once.
2. A completed conversation resumes on its intended warm successor after a real Temporal registration rejection, retaining each message once.
3. Exhausted startup retries return the draft for an explicit retry with the same payload.
4. Permission, question, and plan submissions immediately reveal an editable composer while delivery remains pending.
5. Failed approval delivery restores multi-select answers or feedback. Retrying sends the same response and preserves a separate composer draft.

`startup.ai.spec.ts` runs the first two through real services with Claude and Codex.
`flows-startup-approvals.spec.ts` checks the remaining visible interactions with controlled task API and stream responses.
The controlled suite runs with regular Playwright, or with `.codex/with-flox hogli test:e2e:ai --surface` for an isolated local server.
The task composer attaches entity context; it does not expose file uploads.
These new cases require their own ten-repeat CI validation before being described as stable.

The warm-resume case currently reproduces an extra continuation turn in both runtimes when activation precedes agent readiness.
The successor asks the model to continue the old conversation before processing the new user message.
Replay rejects that undeclared turn even when the eventual follow-up and history assertions pass.
The test remains enabled so this regression blocks the AI check until corrected.

The browser suite runs three cases for each of Claude and Codex:

- Submit from the new-chat composer while a seeded warm workflow waits for registration, recover on the original run, send a follow-up, and reload without duplicate messages.
- Submit while the worker is held, then release it and verify one persisted message and response on the original run.
- Submit one approval through an explicit startup rejection, keep the composer available, and verify exactly one real insight update.

The table below is the broader regression checklist. Controlled browser cases do not establish delivery across real services.
Existing Kea, component, and backend tests cover many individual transitions; they do not establish end-to-end behavior.

| Area                       | Flow and expected result                                                                                                                                          |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cold start                 | Create a chat without a warm run, complete a turn, and send an idle follow-up. Preserve model, permission mode, attachments, and selected context.                |
| Warm resume                | Resume a completed conversation while the successor workflow starts. Preserve history and attachments; deliver once to the intended successor.                    |
| Optimistic approvals       | Answer a question, submit permission feedback, or approve a plan. Queue a follow-up while delivery waits. Restore the same inputs on failure.                     |
| Approval and turn ordering | Hold a follow-up in **Up next** until both approval resolution and turn completion. Exercise either event arriving first.                                         |
| Steering                   | Use **Steer** or Escape to submit the saved queue during an active turn. Preserve the separate draft and verify the agent consumes the queued text once.          |
| Deferred steering          | Request steering while approval delivery waits. Submit only after confirmation; clear the deferred action on failure or replacement.                              |
| Failed queue delivery      | Restore older queued text ahead of newer text and preserve context. Require explicit retry; editing or removing the failed queue allows fresh delivery.           |
| Stopping                   | With no saved queue, Escape or Stop cancels the active turn. Show the Stop spinner and block sends, steering, and approvals until completion.                     |
| Startup stopping           | Request cancellation before attachment or agent readiness. Wait for the current agent and prompt, then cancel once. Leaving the chat cancels the pending intent.  |
| Focus ownership            | Main chat handles Escape while composing or reading. The sidebar handles it only in its composer or approval controls. Menus, dialogs, and editors retain Escape. |
| Sidebar attachment         | Type during startup and retain the draft and focus when the attached run replaces the startup view. Check normal and narrow scenes.                               |
| History and reconnects     | Reload a pending approval, reconnect, or resolve it from another client. Only the owning run's unresolved approval remains actionable.                            |

Keep deadline, token-validation, error-classification, duplicate-click, and stale-completion matrices in the existing backend and Kea tests with controlled clocks.
The browser cases should prove delivery, visible recovery, and persisted effects across service boundaries.
Run runtime-sensitive journeys with both Claude and Codex; test focus and layout variations with the cheaper component or browser surface harness.
