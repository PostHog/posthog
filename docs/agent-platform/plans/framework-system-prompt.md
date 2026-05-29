# Design — framework system prompt

**Status:** draft. **Owner:** ben.

The platform owns part of every agent's system prompt — a preamble that
teaches the model how to behave inside the platform's contract (meta
tools, state machine, tool failure handling, reasoning hints). Today
[`system-prompt.ts`](../../../services/agent-runner/src/loop/system-prompt.ts)
just concatenates `agent.md` with a skills index. This plan fleshes out
the platform half so authors can rely on consistent baseline behaviour
without re-writing the same boilerplate in every `agent.md`.

## 1. Why this needs a doc

Three forces pushing on the system prompt right now:

1. **The session-restart redesign added three meta tools** the model has
   to choose between every turn (`meta-end-turn`, `meta-end-session`,
   `meta-ask-for-input`). Pi-ai gives them to the model with one-line
   descriptions, but the _decision rules_ (when to reach for which) only
   make sense in the context of the platform's state machine — the kind
   of guidance that belongs in a framework preamble, not in every
   author's `agent.md`. See
   [`session-restart-and-state-machine.md`](session-restart-and-state-machine.md).
2. **The approval-gated tools change taught models a new pattern**:
   receive a synthetic queued `tool_result`, surface the link, wait. We
   currently lean on `agent.md` to teach the agent to recognise it, but
   the pattern is platform-wide and belongs in the preamble.
3. **`spec.reasoning` exists** but the model has no idea the author
   opted into a higher thinking budget. Inlining a brief "you have
   extended reasoning available" hint when the spec sets it would let
   the model use it without `agent.md` having to know the knob exists.

Each of these is a paper-cut individually. Together they're the
platform talking to its own runtime without ever telling the model
about itself.

## 2. The split

There are now three layers of instruction the model sees:

```text
┌────────────────────────────────────────────────────────────────┐
│  framework preamble  ← owned by PostHog, injected by runner    │
│  (state machine, meta tools, tool failure, reasoning hints)    │
├────────────────────────────────────────────────────────────────┤
│  agent.md            ← owned by the author, in the bundle      │
│  (what the agent IS, what it should do, how to talk)           │
├────────────────────────────────────────────────────────────────┤
│  conversation        ← user turn, tool_result, assistant turn  │
└────────────────────────────────────────────────────────────────┘
```

**Precedence:** `agent.md` wins. If the author wants the model to
`meta-end-session` on every turn, the framework's "default to
end-turn" guidance loses. The framework preamble is _baseline
behaviour for agents that don't say otherwise_, not policy.

The framework preamble appears **before** `agent.md` so the author can
override with normal natural-language instructions ("Ignore the default
end-turn guidance: this is a one-shot agent. Always call
meta-end-session.")

## 3. Content the framework preamble should cover

### 3.1 Meta-tool catalogue + decision rules

The three meta tools and when to use each. Explicit decision flow so
the model doesn't default to either extreme (closes every session, or
never closes anything).

> You have three control-flow tools always available:
>
> - `@posthog/meta-end-turn` — "I'm done responding for now, but the
>   conversation isn't over." Use this when you've answered the user's
>   message and there might be a follow-up. **This is the default for
>   most turns.** Equivalent to just stopping naturally.
> - `@posthog/meta-ask-for-input` — same effect as `end-turn`, but
>   signals to the user-facing client that you're waiting on a specific
>   answer. Use when you need a particular piece of information to
>   continue (e.g. "what's your account id?").
> - `@posthog/meta-end-session` — **hard close.** The user can NOT
>   continue this conversation unless the agent's author opted into
>   restart. Only use this when the agent's task is genuinely complete
>   and there's nothing the user could meaningfully say next. (Example:
>   a one-shot reporting agent that has delivered its summary.)
>
> When in doubt, prefer `meta-end-turn`. Closing a session prematurely
> can't be undone.

### 3.2 Conversation-state contract

What `completed` and `closed` mean from the model's point of view.

> Between your turns the session sits in one of two states the user
> might encounter:
>
> - `completed` — your last turn ended cleanly. The user can keep
>   talking. From your perspective this is the same as "the model's
>   most recent message was the last one in the conversation."
> - `closed` — you called `meta-end-session`. The user can't send
>   anything further. If you see a tool_result that says "approval"
>   queued, see §3.4 — that's NOT the same as `closed`.

### 3.3 Tool failure handling

How to recover when a tool dispatch fails. Current behaviour: the model
sees a `tool_result` with `isError: true` and improvises. We can
give it a structured decision flow.

> When a tool you called returns an error:
>
> 1. **Re-read the args.** Most tool failures are bad arguments —
>    string vs int, missing required field, malformed JSON. Inspect
>    the error message and fix the next call.
> 2. **Don't retry blindly.** If the same call fails twice with the
>    same args, the issue is the args or the tool, not transient. Pick
>    a different approach, ask the user, or end the turn.
> 3. **Surface errors the user cares about.** "I couldn't post to
>    #engineering because the channel doesn't exist" is more useful
>    than silently retrying with a different channel id.

### 3.4 Approval-gated tool results

The synthetic `queued` envelope shape — what to do when the model sees
it. Currently authors have to remember to instruct the model; the
framework can do this once.

> Some tools require human approval before they actually run. When the
> platform queues an approval, you'll see a `tool_result` whose
> content is JSON like:
>
> ```jsonc
> {
>   "approval": {
>     "request_id": "ar_…",
>     "state": "queued",
>     "approval_url": "https://posthog.com/agents/<slug>/approvals/ar_…",
>   },
> }
> ```
>
> When you see this:
>
> 1. **Don't retry the tool call.** It's queued. Re-issuing with the
>    same args dedupes to the same row.
> 2. **Tell the user what you queued and share the `approval_url`** so
>    the right person can act on it.
> 3. **Continue the conversation.** The platform will inject a
>    follow-up `user` message when the approver decides — at that
>    point you can summarise the result or react to a rejection.

### 3.5 Reasoning-budget hint

Only when `spec.reasoning` is set. A one-line nudge that the author
has opted into higher thinking budget.

> _(injected only when `spec.reasoning` ∈ {high, xhigh})_
>
> This agent has extended reasoning enabled. Take more time to plan
> tool calls and think through edge cases before responding; the
> platform has budgeted for it.

### 3.6 Skills index

Already present — moved to the framework section so it's clearly
"platform-injected" not "author-injected." No behavioural change.

## 4. Authoring affordances

The framework preamble is opaque to authors today. After this:

- **`agent-applications-revisions-preview-prompt`** _(new MCP tool)_ —
  returns the fully-assembled system prompt for a given revision so the
  authoring AI can inspect what the model will actually see.
- **`agent.md`-level overrides** — three magic markers an author can
  include to selectively suppress framework sections:

  ```md
  <!-- posthog:framework:omit_meta_tool_guidance -->
  <!-- posthog:framework:omit_tool_failure_guidance -->
  <!-- posthog:framework:omit_approval_guidance -->
  ```

  Detected by `system-prompt.ts` at assembly time. Conservative scoping
  so authors don't accidentally turn the whole preamble off — there's
  no `omit_all`.

## 5. Measuring adherence

The framework preamble is only useful if real models actually follow
it. Add to [`real-inference.test.ts`](../../../services/agent-tests/src/cases/real-inference.test.ts):

- **Meta-tool decision test** — script an agent without any author-side
  override; ask it a question with no clear "task complete" signal;
  assert the session ends in `completed` (open), not `closed`.
- **Approval-gating test** — already exists; the new framework guidance
  should make it more robust (less reliant on author-side reminders in
  `agent.md`).
- **Tool failure recovery test** — call a tool with a deliberately
  malformed arg; assert the model surfaces the error to the user in
  human terms rather than crashing or silently retrying.

Track pass/fail across the provider matrix so we catch
provider-specific drift (e.g. Anthropic obeying the preamble; OpenAI
ignoring it).

## 6. Rollout

Three slices, sequenced:

1. **Skeleton** — add the framework-preamble assembly to
   `system-prompt.ts` with §3.1 (meta-tool catalogue) and §3.2
   (state contract) wired in. Default-on; no override markers yet.
   Ship the meta-tool decision test from §5.
2. **Tool failure + approval guidance** — add §3.3 and §3.4. Wire the
   author-side override markers (§4) and the
   `agent-applications-revisions-preview-prompt` MCP tool.
3. **Reasoning hint** — add §3.5 (gated on `spec.reasoning`). Cheap
   and low-risk; ships last because it depends on (1) and (2) for
   the assembly machinery.

## 7. Open questions

1. **Length budget.** The platform preamble eats input tokens on every
   turn. §3.1–§3.4 alone is maybe ~300–500 tokens. Should we cache it
   via Anthropic's prompt caching when available so the per-turn cost
   is amortised? Probably yes; non-blocking.
2. **Localisation.** Multi-lingual `agent.md`s exist; an English
   framework preamble surrounding a Japanese `agent.md` is weird. v0
   ships English-only; revisit when an author actually asks.
3. **Version skew.** When we evolve the preamble, frozen revisions
   keep getting the new content. Is that what we want? Probably yes —
   the framework half is platform behaviour, not agent behaviour. But
   call it out so authors know "the same revision can behave slightly
   differently after a platform upgrade." Consider stamping the
   preamble version into `session_started` analytics so we can
   correlate behaviour shifts.
4. **Override-marker discoverability.** `<!-- posthog:framework:omit_…
-->` is invisible to anyone reading the `agent.md`. Maybe a real
   `spec.framework_prompt: { omit: [...] }` field is cleaner, at the
   cost of bumping the spec schema. Lean toward the schema field once
   we know which overrides actually matter.

## 8. Composes with

- `session-restart-and-state-machine.md` — the meta-tool catalogue
  refers to it.
- `approval-gated-tools.md` — §3.4 reflects the wire format from there.
- `streaming-and-reasoning.md` — §3.5 reflects the `spec.reasoning`
  surface from there.
- `agent-authoring-flow.md` — once §4's `preview-prompt` MCP tool
  exists, authoring AIs can inspect their agent's effective prompt
  before promotion. Update that plan's "TEST" phase to mention it.
