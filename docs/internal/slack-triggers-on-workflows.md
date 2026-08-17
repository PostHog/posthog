# Slack triggers on workflows, instead of loops

Status: proposal

## Context

Loops and workflows solve the same shape of problem: something happens, match it, run something in response.
Loops built its own half of that stack, including trigger matching, poster gating, dedupe, rate caps, overlap policy and run records.

Building a Slack trigger for loops surfaced the cost of that duplication.
Four capabilities existed on the loops backend with no UI able to reach them, and one of them had never worked end to end, because save-time validation and run-time mounting accepted disjoint sets of MCP installations.
Each of those is a general problem that the workflows engine already solves once.

This document proposes building the Slack trigger on workflows instead, and treating loops as the thing that gets superseded rather than extended.

## The decision

Slack messages enter as **internal events**, not through standard capture.

They are PostHog-internal signals rather than customer analytics.
Routing them through `capture_internal` (`posthog/api/capture.py`) would mean they pass through capture-rs and count against the customer's quotas, billing and event stream, which is wrong for a control-plane signal.
`produce_internal_event` (`posthog/cdp/internal_events.py`) publishes to the `cdp_internal_events` topic and avoids all of that.

This is the more correct model and it costs one piece of engine work, described below.
The conversations product took the other path for `$conversation_message_sent`, so both are established; the difference is whether the event is a customer-visible analytics fact or an internal signal.

## How the pieces stand today

Traced through the code:

- `produce_internal_event` publishes to `cdp_internal_events`.
- `CdpInternalEventsConsumer` (`nodejs/src/cdp/consumers/cdp-internal-event.consumer.ts`) reads that topic and builds **hog function** invocations only. It declares `hogTypes: ['internal_destination']` and never constructs a `HogFlowInvocationPipeline`.
- `CdpHogflowSubscriptionMatcherConsumer` also reads the topic, but only to wake workflow runs already parked on a wait.

So an internal event can wake a parked workflow today, and cannot start one.
That is the gap.

By contrast `cdp-events.consumer.ts` and `cdp-data-warehouse-events.consumer.ts` both build hog function and HogFlow invocations side by side, each selecting flows with an `eligibilityFn` on the trigger type.

Two things make closing the gap smaller than it appears:

- `convertInternalEventToHogFunctionInvocationGlobals` (`nodejs/src/cdp/utils.ts`) already produces the globals shape the HogFlow pipeline consumes, with `person` optional.
- Person-less triggers are precedented. The data warehouse trigger is explicitly row-scoped and person-less, so the executor already tolerates a run with no person attached.

## What has to be built

### 1. Emit the event

Publish `$slack_message_received` from the Slack event handler with `produce_internal_event`.
Properties carry channel id and name, workspace id, poster id, whether the poster is a person or an app, message text, thread timestamp and permalink.

This replaces `loop_slack_events.py` in the loops implementation, where matching, poster gating, keyword filters, payload conditions, dedupe and the per-channel throttle are all hand-written.
On workflows they become engine concerns.

### 2. Add a trigger type

Add the type to `TRIGGER_TYPES` in `products/workflows/backend/models/hog_flow/hog_flow.py`, add the matching zod literal in `nodejs/src/cdp/schema/hogflow.ts`, and add a validation branch in `products/workflows/backend/api/hog_flow.py` that forces the filter source.

Follow the `data-warehouse-table` branch in that file, which sets `filters["source"] = "data-warehouse-table"` so only the intended payload is considered.

### 3. Build HogFlow invocations from internal events

Give `CdpInternalEventsConsumer` a `HogFlowInvocationPipeline` alongside its existing hog function pipeline.

`cdp-data-warehouse-events.consumer.ts` is an exact template: run both `buildInvocations` calls in parallel, select flows with an `eligibilityFn` on the trigger type, concatenate the results, then emit a `running` lifecycle row per invocation so the runs UI shows them in flight.

### 4. Trigger UI

Add a registry entry under `products/workflows/frontend/Workflows/hogflows/registry/triggers/`.

`conversations.tsx` is the closest analogue at 223 lines: it is message-shaped, it renders a curated set of events with labels, and it writes a standard trigger config rather than exposing raw filter internals.
The registry is pluggable, so `StepTrigger.tsx` does not need to change.

### 5. A create-task action

Add a destination template under `nodejs/src/cdp/templates/_destinations/` that creates an AI task from a prompt, skills, MCP connectors and repository, plus the task-creation endpoint it calls.

`posthog_conversations` is the precedent for a destination that calls another PostHog product.
Once the template exists it is available as a `function` action to every workflow, not only Slack-triggered ones.

## What we give up

**Internal events are not stored in ClickHouse.**
Only the two CDP consumers read that topic and neither writes to a table.

Two consequences:

- The filter UI cannot autocomplete property values from real data. It has to be driven by curated options and taxonomy definitions. The conversations trigger already works this way, so this is a constraint on the design rather than a new problem.
- There is no `SELECT ... FROM events` to see what Slack actually sent. Debugging runs through workflow invocations and logs.

**Overlap policy has no direct equivalent.**
`trigger_masking` dedups and samples which firings start a run; it does not cap how many runs are in flight at once.
A loop can be set to skip, run in parallel, or cancel the previous run. If that behavior matters, it needs designing rather than assuming.

## Effort compared with the loops approach

The loops implementation splits across two branches, one for the backend trigger and one for the desktop configuration UI.
Behind them sit roughly 4,100 lines of loops backend across `loop_runs.py`, `loop_slack_events.py`, `facade/loops.py` and `serializers_loops.py`, and roughly 8,000 lines of desktop loops UI.
`loop_slack_events.py` alone is 521 lines of matching and gating.

The workflows version adds five small pieces, four of which have a file to copy, and reuses the engine for everything else: trigger matching, property filtering, dedupe, branching, delays, retries, per-step logs, step-by-step test runs before enabling, draft and publish with an impact preview, and revision history with rollback.

The trade is that trigger configuration lives in the workflows editor rather than the desktop loop form.

## Open questions

1. **Do loops get frozen or migrated?**
   Freezing and building new work on workflows carries no migration cost and leaves two systems running.
   Migrating means porting loop configuration into workflow actions and moving live loops, and the desktop UI is the bulk of that work.
   Recommendation: build the Slack trigger and the create-task action on workflows, run both side by side, and decide from evidence.

2. **What replaces overlap policy?**
   See above. Worth settling before the first workflow-triggered task ships, because it changes what a busy channel does.

3. **Should other internal events become triggerable at the same time?**
   Once step 3 lands, every event on `cdp_internal_events` can start a workflow, including the error tracking issue lifecycle events.
   That is a larger product surface than the Slack case and should be an explicit decision rather than a side effect.

## Verification

- **Emit:** publish a message from the Slack handler and confirm it reaches the topic. Internal events are not queryable in ClickHouse, so assert on the producer result and the consumer's metrics rather than on a table.
- **Trigger:** create a workflow with the new trigger type, enable it, post in a channel, then confirm a run exists with `workflows-list-invocations` and read the path with `workflows-logs`.
- **Filtering UI:** open the workflow in the editor and confirm the trigger renders and round-trips its configuration without falling back to the raw filter editor.
- **Task action:** use `workflows-test-run` step by step with `mock_async_functions=false` and confirm the task is created with the expected prompt, skills and connectors.
- **No regression:** the existing loops tests stay green for as long as both systems coexist.
