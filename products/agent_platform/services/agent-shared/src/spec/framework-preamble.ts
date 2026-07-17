/**
 * Framework system-prompt preamble — the platform half of every agent's
 * system prompt. Owned by PostHog and injected before the bundle's
 * `agent.md`, this teaches the model how to behave inside the platform's
 * contract (state machine, meta tools, tool failure handling, approval
 * flow, reasoning hints).
 *
 * Versioning: bump `FRAMEWORK_PROMPT_VERSION` whenever the preamble
 * changes meaningfully (decision rules shifting, sections renamed,
 * behavioural defaults flipped). Stable wording tweaks don't need a
 * bump. The runner stamps the active version onto `session_started`
 * analytics so we can correlate behaviour shifts with preamble
 * versions in real-inference runs.
 */

import { AgentRevision, FrameworkPromptSection } from './spec'

export const FRAMEWORK_PROMPT_VERSION = 1

/**
 * Decision rules for the two always-on meta tools. Plan §3.1.
 *
 * The model gets these via pi-ai with one-line descriptions; the
 * preamble teaches WHEN to reach for each. Default-first framing
 * (`meta-end-turn`) keeps the model from defaulting to either extreme
 * (closing every session, or never closing anything).
 */
const META_TOOL_GUIDANCE = `
## Ending your turn

You have two control-flow tools always available. Choose deliberately
between them — they both "end the turn" but they mean different things
to the user.

- \`@posthog/meta-end-turn\` — "I'm done responding for now, but the
  conversation isn't over." Use this when you've answered the user's
  message and there might be a follow-up. **This is the default for
  most turns.** Equivalent to just stopping naturally. If you need the
  user to answer a specific question, just write the question as your
  reply and end the turn — there is no separate "ask for input" tool.
- \`@posthog/meta-end-session\` — **hard close.** The user cannot
  continue this conversation unless the agent's author opted into
  restart. Only use this when the agent's task is genuinely complete
  and there is nothing the user could meaningfully say next. Example:
  a one-shot reporting agent that has delivered its summary.

When in doubt, prefer \`meta-end-turn\`. Closing a session prematurely
cannot be undone.
`.trim()

/**
 * Conversation-state contract from the model's point of view. Plan §3.2.
 *
 * Explains the open vs terminal distinction without leaking internal
 * implementation details (queued/running). The model only ever sees the
 * "between your turns" view.
 */
const STATE_CONTRACT = `
## Conversation state

Between your turns the session sits in one of two states the user might
encounter:

- \`completed\` — your last turn ended cleanly. The user can keep
  talking. From your perspective this is the same as "the most recent
  message in the conversation was yours."
- \`closed\` — you called \`meta-end-session\`. The user cannot send
  anything further.
`.trim()

/**
 * Tool failure recovery decision flow. Plan §3.3.
 *
 * Default model behaviour on tool error: improvise. The framework
 * teaches a structured flow so the model surfaces errors the user
 * cares about instead of silently retrying.
 */
const TOOL_FAILURE_GUIDANCE = `
## When a tool you called returns an error

1. **Re-read the args.** Most tool failures are bad arguments — string
   vs int, missing required field, malformed JSON. Inspect the error
   message and fix the next call.
2. **Don't retry blindly.** If the same call fails twice with the same
   args, the issue is the args or the tool, not transient. Pick a
   different approach, ask the user, or end the turn.
3. **Surface errors the user cares about.** "I couldn't post to
   #engineering because the channel doesn't exist" is more useful than
   silently retrying with a different channel id.
`.trim()

/**
 * Approval-gated tool result handling. Plan §3.4.
 *
 * The synthetic queued envelope shape is platform-specific — authors
 * shouldn't need to remember the JSON wire format. The framework
 * documents it once.
 */
const APPROVAL_GUIDANCE = `
## Approval-gated tools

Some tools require human approval before they actually run. When the
platform queues an approval, you will see a \`tool_result\` whose
content is JSON like:

\`\`\`json
{
  "approval": {
    "request_id": "ar_...",
    "state": "queued",
    "approval_url": "posthog-code://approval/ar_..."
  }
}
\`\`\`

When you see this:

1. **Don't retry the tool call.** It's queued. Re-issuing with the same
   args dedupes to the same row.
2. **Tell the user what you queued and share the \`approval_url\`** so
   the right person can act on it.
3. **Continue the conversation.** The platform will inject a follow-up
   \`user\` message when the approver decides — at that point you can
   summarise the result or react to a rejection.
`.trim()

/**
 * Reasoning-budget hint. Plan §3.5.
 *
 * Only injected when the spec has opted into a high-thinking-budget
 * reasoning level. Lower levels (minimal / low / medium) get nothing —
 * those are normal model behaviour, not a signal worth amplifying.
 */
const REASONING_HINT = `
## Reasoning budget

This agent has extended reasoning enabled. Take more time to plan tool
calls and think through edge cases before responding; the platform has
budgeted for it.
`.trim()

const PREAMBLE_HEADER = `
# Platform guidance

The following section is platform-managed guidance about how to
behave inside this agent runtime. The author's instructions appear
after this section and override anything here.
`.trim()

const PREAMBLE_FOOTER = `
---

# Agent
`.trim()

export interface FrameworkPreambleOpts {
    /**
     * Sections to omit from the preamble. Wired from
     * `spec.framework_prompt.omit` at the call site. An empty array (or
     * undefined) renders every section.
     */
    omit?: FrameworkPromptSection[]
}

/**
 * Render the framework preamble for one revision. Returns the markdown
 * string the runner prepends to the bundle's `agent.md`.
 *
 * Stateless — the same input always produces the same output. The
 * runner stamps `FRAMEWORK_PROMPT_VERSION` onto `session_started`
 * analytics separately; nothing about the rendered text needs to
 * encode the version.
 */
export function renderFrameworkPreamble(rev: AgentRevision, opts: FrameworkPreambleOpts = {}): string {
    const omit = new Set<FrameworkPromptSection>([...(opts.omit ?? []), ...(rev.spec.framework_prompt?.omit ?? [])])
    const sections: string[] = [PREAMBLE_HEADER]
    if (!omit.has('meta_tool_guidance')) {
        sections.push(META_TOOL_GUIDANCE)
    }
    if (!omit.has('state_contract')) {
        sections.push(STATE_CONTRACT)
    }
    if (!omit.has('tool_failure_guidance')) {
        sections.push(TOOL_FAILURE_GUIDANCE)
    }
    if (!omit.has('approval_guidance')) {
        sections.push(APPROVAL_GUIDANCE)
    }
    // Reasoning hint is doubly-gated: spec.reasoning has to be a
    // high-budget level AND the author hasn't opted out via omit. Low
    // reasoning levels are normal model behaviour and don't need
    // amplification.
    const reasoningLevel = rev.spec.reasoning
    const wantReasoningHint = reasoningLevel === 'high' || reasoningLevel === 'xhigh'
    if (wantReasoningHint && !omit.has('reasoning_hint')) {
        sections.push(REASONING_HINT)
    }
    sections.push(PREAMBLE_FOOTER)
    return sections.join('\n\n')
}
