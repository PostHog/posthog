/**
 * Multi-model fallback wrapper around a base `StreamFn`. Tries a priority list
 * (primary first) in order; retries the next model on a fallback-eligible
 * failure, else stops. Eligible = transient/provider-side (5xx/conn/timeout/429
 * via `isFallbackEligible`); NOT permanent 4xx or aborts. Commit guard: once a
 * content-bearing event is forwarded the turn is committed and we can't fall
 * over (a bare `start` doesn't count). Capped at the list length.
 */

import type { StreamFn } from '@earendil-works/pi-agent-core'
import type { AssistantMessage, AssistantMessageEvent, AssistantMessageEventStream, Model } from '@earendil-works/pi-ai'
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai'

import { categorize, ReasoningEffort } from '@posthog/agent-shared'

import { classifyGatewayError } from './gateway-error'

/** A model from the policy list, resolved to a concrete pi-ai Model + its reasoning knob. */
export interface ResolvedModel {
    model: Model<string>
    reasoning?: ReasoningEffort
}

/** Content-bearing event types — forwarding any of these commits the turn downstream. */
function isContentEvent(e: AssistantMessageEvent): boolean {
    return e.type !== 'start' && e.type !== 'error'
}

/**
 * A pre-commit failure is fallback-eligible only when transient/provider-side:
 * 5xx / conn / timeout / 429. Permanent client errors (bad_request / non-429
 * 4xx) and aborts are NOT eligible.
 *
 * `categorize()` covers conn/timeout (`transient_infra`) and 429/quota
 * (`quota_exhausted`); `classifyGatewayError` adds the HTTP-status signal so a
 * bare `5xx` (which categorize doesn't pattern-match) is eligible and a non-429
 * 4xx is hard-excluded even if a substring would otherwise match.
 */
export function isFallbackEligible(errorMessage: string | undefined): boolean {
    const reason = errorMessage ?? ''
    const g = classifyGatewayError(reason)
    // Permanent client status (any non-429 4xx) → never eligible.
    if (g && g.status >= 400 && g.status < 500 && g.status !== 429) {
        return false
    }
    // 5xx upstream / 429 throttle off the status prefix → eligible.
    if (g && (g.status >= 500 || g.status === 429)) {
        return true
    }
    const cat = categorize(reason)
    return cat === 'transient_infra' || cat === 'quota_exhausted'
}

/** Notified on each fall-over so the caller can mark analytics. */
export interface FallbackHooks {
    /** The model that just answered, with its ORIGINAL policy index (0-based).
     *  >0 means a non-primary model served (a fallover this turn, or a sticky
     *  lead carried over from a prior turn). */
    onAttempt?: (index: number, model: Model<string>) => void
    /** A model was skipped after a fallback-eligible failure (original index). */
    onFallback?: (fromIndex: number, fromModel: Model<string>, reason: string | undefined) => void
    /** The session's sticky model is no longer in the `models` list (delisted
     *  from the gateway or removed from the spec), so the pin is broken and
     *  attempt order falls back to the policy primary. Surfaced so the caller
     *  can record the cache-warmth regression — otherwise it shows up only
     *  indirectly as a lower prompt-cache hit rate. */
    onPinLost?: (servedId: string) => void
}

/** Session-stability knobs. See `ModelOptimizeForSchema` in agent-shared. */
export interface FallbackStickiness {
    /**
     * `cost` (default): once a model has served a turn, pin to it — every later
     * turn uses ONLY that model, no cross-model failover (keeps the provider's
     * prompt cache warm). `availability`: lead with the sticky model but still
     * fail over to the rest of the list on failure.
     */
    optimizeFor?: 'cost' | 'availability'
    /**
     * The model that served the previous turn (e.g. read off a resumed
     * conversation's last assistant message). Seeds the sticky lead / the pin so
     * stickiness survives suspend→resume, not just consecutive in-process turns.
     */
    initialServedId?: string
}

/** Original-policy-indexed view of a model, so hooks report the policy position
 *  regardless of the per-turn attempt order. */
interface IndexedModel {
    entry: ResolvedModel
    index: number
}

/**
 * The attempt order for one turn:
 *  - no model served yet → full list in priority order (walk to find one).
 *  - `cost` + a served model → just that model (no failover).
 *  - `availability` + a served model → that model first, then the rest in
 *    priority order (sticky lead + failover).
 */
function attemptOrder(models: ResolvedModel[], servedId: string | undefined, optimizeFor: string): IndexedModel[] {
    const indexed: IndexedModel[] = models.map((entry, index) => ({ entry, index }))
    if (!servedId) {
        return indexed
    }
    const pos = indexed.findIndex((x) => x.entry.model.id === servedId)
    if (pos < 0) {
        return indexed
    }
    if (optimizeFor === 'cost') {
        return [indexed[pos]]
    }
    const [lead] = indexed.splice(pos, 1)
    return [lead, ...indexed]
}

/**
 * Build a `StreamFn` that walks `models` in priority order. The `model` arg the
 * loop passes is ignored — this owns model selection — but each attempt honours
 * the caller's `options` (apiKey, headers, signal) with the entry's `reasoning`
 * applied on top.
 *
 * Session-sticky: across turns the wrapper remembers the model that last served
 * and prefers it, so the provider's prompt cache stays warm rather than
 * thrashing. `stickiness.optimizeFor` decides what happens on a later failure —
 * `cost` pins (no failover), `availability` falls over. See `attemptOrder`.
 */
export function fallbackStreamFn(
    base: StreamFn,
    models: ResolvedModel[],
    hooks?: FallbackHooks,
    stickiness?: FallbackStickiness
): StreamFn {
    if (models.length === 0) {
        throw new Error('fallbackStreamFn requires at least one model')
    }
    const optimizeFor = stickiness?.optimizeFor ?? 'cost'
    // The model that served the most recent successful turn; persists across
    // turns within this wrapped fn. Seeded from a resumed conversation.
    let servedId = stickiness?.initialServedId
    return (_model, context, options) => {
        // `servedId` is set but no longer in the models list — the pin has
        // been broken (the model was delisted, or `models` was edited).
        // Surface it via `onPinLost` so the caller can log / mark analytics;
        // `attemptOrder` will return the full list and we'll repick from
        // primary. Done here (not inside the IIFE) so a missing hook
        // doesn't depend on whether `attemptOrder` is reached.
        if (servedId && !models.some((m) => m.model.id === servedId)) {
            hooks?.onPinLost?.(servedId)
            servedId = undefined
        }
        const order = attemptOrder(models, servedId, optimizeFor)
        const out = createAssistantMessageEventStream()
        // Track current attempt so the outer guard knows whether we've
        // committed when something unexpected throws inside the IIFE.
        let lastEntry: ResolvedModel = order[0].entry
        let lastCommitted = false
        const run = async (): Promise<void> => {
            for (let pos = 0; pos < order.length; pos++) {
                const { entry, index } = order[pos]
                lastEntry = entry
                const last = pos === order.length - 1
                const opts = { ...options, reasoning: entry.reasoning ?? options?.reasoning }
                let committed = false
                try {
                    const stream = await base(entry.model, context, opts)
                    const buffered: AssistantMessageEvent[] = []
                    for await (const event of stream) {
                        if (committed) {
                            out.push(event)
                            continue
                        }
                        if (isContentEvent(event)) {
                            // First real progress — commit: flush buffered envelope + this event.
                            committed = true
                            lastCommitted = true
                            servedId = entry.model.id
                            hooks?.onAttempt?.(index, entry.model)
                            for (const b of buffered) {
                                out.push(b)
                            }
                            buffered.length = 0
                            out.push(event)
                            continue
                        }
                        // Bare `start` / pre-commit `error`: hold until we know the outcome.
                        buffered.push(event)
                    }
                    const result = await stream.result()
                    if (committed) {
                        out.end(result)
                        return
                    }
                    // Stream ended before any content: a pure success (rare) or a
                    // pre-commit failure. Success → forward + done. Failure →
                    // fall over when eligible and attempts remain.
                    const failed = result.stopReason === 'error' || result.stopReason === 'aborted'
                    if (!failed) {
                        servedId = entry.model.id
                        hooks?.onAttempt?.(index, entry.model)
                        for (const b of buffered) {
                            out.push(b)
                        }
                        out.end(result)
                        return
                    }
                    if (!last && result.stopReason === 'error' && isFallbackEligible(result.errorMessage)) {
                        hooks?.onFallback?.(index, entry.model, result.errorMessage)
                        continue
                    }
                    // Permanent / abort / exhausted / cost-pinned: surface this failure downstream.
                    hooks?.onAttempt?.(index, entry.model)
                    for (const b of buffered) {
                        out.push(b)
                    }
                    out.end(result)
                    return
                } catch (err) {
                    // The contract says base must not throw; defensively treat a
                    // throw as a pre-commit failure (we never forwarded anything,
                    // so we can still fall over). Once committed, re-raise to the
                    // outer guard, which surfaces it on the stream — never let the
                    // promise float (would leave callers awaiting `.result()` hung).
                    if (committed) {
                        throw err
                    }
                    const reason = err instanceof Error ? err.message : String(err)
                    if (!last && isFallbackEligible(reason)) {
                        hooks?.onFallback?.(index, entry.model, reason)
                        continue
                    }
                    const message: AssistantMessage = {
                        role: 'assistant',
                        content: [],
                        api: entry.model.api,
                        provider: entry.model.provider,
                        model: entry.model.id,
                        usage: {
                            input: 0,
                            output: 0,
                            cacheRead: 0,
                            cacheWrite: 0,
                            totalTokens: 0,
                            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
                        },
                        stopReason: 'error',
                        errorMessage: reason,
                        timestamp: Date.now(),
                    }
                    hooks?.onAttempt?.(index, entry.model)
                    out.push({ type: 'error', reason: 'error', error: message })
                    out.end(message)
                    return
                }
            }
        }
        // No matter how `run` exits — normal completion, post-commit re-throw,
        // or an unexpected throw from `out.push` / destructuring / `base()` not
        // matching the no-throw contract — we MUST end the stream so callers
        // awaiting `.result()` don't hang.
        run().catch((err) => {
            const reason = err instanceof Error ? err.message : String(err)
            const message: AssistantMessage = {
                role: 'assistant',
                content: [],
                api: lastEntry.model.api,
                provider: lastEntry.model.provider,
                model: lastEntry.model.id,
                usage: {
                    input: 0,
                    output: 0,
                    cacheRead: 0,
                    cacheWrite: 0,
                    totalTokens: 0,
                    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
                },
                stopReason: 'error',
                errorMessage: reason,
                timestamp: Date.now(),
            }
            if (!lastCommitted) {
                out.push({ type: 'error', reason: 'error', error: message })
            }
            out.end(message)
        })
        return out as AssistantMessageEventStream
    }
}
