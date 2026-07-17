/**
 * Out-of-band notification when a session reaches a terminal `failed` state.
 *
 * The runner already publishes a `failed` bus event, writes a `failed`
 * log_entries row, and appends a synthetic assistant turn to the
 * conversation. None of that reaches an external surface — a Slack-triggered
 * session that crashes pre-runSession leaves the originating thread silent.
 * The notifier closes that gap: it posts a sanitized message back to whatever
 * channel triggered the session, keyed off `AgentSession.trigger_metadata`.
 *
 * Discipline: notifiers MUST NOT throw. A failure inside the notifier
 * surfaces as a logged warning and returns — never as a second
 * `session.crashed`. The runner invokes the notifier *after*
 * `queue.update(state: 'failed')` so a notifier crash can't strand the
 * session in a non-terminal state.
 *
 * Sanitization is the load-bearing decision. Raw reasons can leak infra
 * detail (docker image refs, MCP transport URLs, decrypt failures); we map
 * them to a small fixed enum of user-facing categories and a stable string
 * per category. Owner-facing debug stays in log_entries.
 */

import { AgentApplication, AgentRevision, AgentSession } from '../spec/spec'

/**
 * Coarse, user-facing buckets the notifier maps every failure to. The bus
 * `failed` event and the session conversation's synthetic assistant turn
 * also reuse this — single source of truth for "what does the user see."
 */
export type FailureCategory =
    | 'transient_infra'
    | 'configuration'
    | 'quota_exhausted'
    | 'tool_error'
    | 'capability_mismatch'
    | 'unknown'

export interface FailureNotifierInput {
    session: AgentSession
    application: AgentApplication
    /** The resolved/hit revision this session ran. Carries the `encrypted_env`
     *  the notifier resolves its outbound secret (e.g. Slack bot token) from. */
    revision: AgentRevision
    /** Raw reason — owner-facing only. Never reaches the notifier's output channel. */
    reason: string
    category: FailureCategory
}

export interface FailureNotifier {
    /** Fire-and-forget. MUST swallow its own errors. */
    notify(input: FailureNotifierInput): Promise<void>
}

/**
 * Default. Used by every session whose trigger has no out-of-band channel
 * to notify (direct chat, MCP, webhook v1) and by the harness unless a test
 * explicitly wires a real notifier.
 */
export class NoopFailureNotifier implements FailureNotifier {
    async notify(_input: FailureNotifierInput): Promise<void> {
        // intentional no-op
    }
}

/**
 * Dispatch by `trigger_metadata.kind`. The runner wires this with one or
 * more per-trigger sub-notifiers; kinds without a registered sub-notifier
 * fall through silently. Sub-notifier failures are caught and logged here
 * so a single misbehaving channel can't crash the dispatcher.
 */
export class TriggerAwareFailureNotifier implements FailureNotifier {
    constructor(
        private readonly registry: Partial<Record<string, FailureNotifier>>,
        private readonly logger?: { warn: (meta: Record<string, unknown>, msg: string) => void }
    ) {}

    async notify(input: FailureNotifierInput): Promise<void> {
        const meta = input.session.trigger_metadata
        if (!meta) {
            return
        }
        const sub = this.registry[meta.kind]
        if (!sub) {
            return
        }
        try {
            await sub.notify(input)
        } catch (err) {
            this.logger?.warn(
                {
                    session_id: input.session.id,
                    trigger_kind: meta.kind,
                    err: err instanceof Error ? err.message : String(err),
                },
                'failure_notifier_dispatch_threw'
            )
        }
    }
}

/**
 * Categorize a raw failure reason into the user-facing enum. Defaults to
 * `unknown` on no-match — never falls through to raw, by design. Add new
 * patterns conservatively: a wrong category is much worse than `unknown`.
 *
 * Patterns drawn from observed failure modes in `worker.ts`'s pre-runSession
 * catch (sandbox acquire, MCP open, secret resolve) and `driver.ts`'s
 * `emitFailure` (model_error, loop_error, max_turns_exceeded, output_truncated).
 */
export function categorize(reason: string): FailureCategory {
    const r = reason.toLowerCase()
    if (
        r.includes('docker') ||
        r.includes('pull access denied') ||
        r.includes('unable to find image') ||
        r.includes('modal') ||
        r.includes('sandbox') ||
        r.includes('kafka') ||
        r.includes('redis') ||
        r.includes('postgres') ||
        r.includes('econnrefused') ||
        r.includes('etimedout') ||
        r.includes('econnreset') ||
        r.includes('socket hang up')
    ) {
        return 'transient_infra'
    }
    if (
        r.includes('missing required secret') ||
        r.includes('signing_secret') ||
        r.includes('invalid spec') ||
        r.includes('mcp_transport') ||
        r.includes('mcp open failed') ||
        r.includes('no_bot_token') ||
        r.includes('bundle_missing') ||
        r.includes('revision_missing') ||
        r.includes('integration_host_validator') ||
        r.includes('encryption') ||
        r.includes('client_tool_dispatcher_unavailable')
    ) {
        return 'configuration'
    }
    if (
        r.includes('429') ||
        r.includes('rate_limit') ||
        r.includes('rate limit') ||
        r.includes('max_turns_exceeded') ||
        r.includes('output_truncated') ||
        r.includes('quota')
    ) {
        return 'quota_exhausted'
    }
    if (r.includes('tool threw') || r.includes('tool_call_failed') || r.includes('sandbox timeout')) {
        return 'tool_error'
    }
    // `client_tool_unsupported:<id>` is thrown by build-agent-tools.ts when a
    // chat caller did not declare a `required:true` client tool. The user's
    // client is out of date or doesn't support the tool — neither a
    // misconfiguration nor an infra issue.
    if (r.includes('client_tool_unsupported')) {
        return 'capability_mismatch'
    }
    return 'unknown'
}

const MESSAGES: Record<FailureCategory, string> = {
    transient_infra: 'Something went wrong on our side. Please try again in a moment.',
    configuration: "This agent isn't configured correctly. The agent owner has been notified.",
    quota_exhausted: "I've hit a usage limit on this conversation. Please try again later.",
    tool_error: 'I ran into an error while using one of my tools. The agent owner can see details.',
    capability_mismatch:
        "This agent needs a tool your client doesn't support. Please update your client or contact the agent owner.",
    unknown: "I wasn't able to respond to that. The agent owner has been notified.",
}

/**
 * Stable, sanitized user-facing string per category. Used by the notifier's
 * outbound message AND by the runner's synthetic conversation turn, so the
 * conversation transcript and the channel reply stay in lockstep.
 */
export function userFacingMessage(category: FailureCategory): string {
    return MESSAGES[category]
}
