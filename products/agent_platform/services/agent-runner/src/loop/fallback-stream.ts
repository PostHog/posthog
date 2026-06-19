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
    /** The attempt that just answered (0-based index into `models`). */
    onAttempt?: (index: number, model: Model<string>) => void
    /** A model was skipped after a fallback-eligible failure. */
    onFallback?: (fromIndex: number, fromModel: Model<string>, reason: string | undefined) => void
}

/**
 * Build a `StreamFn` that walks `models` in priority order. The `model` arg the
 * loop passes is ignored — this owns model selection — but each attempt honours
 * the caller's `options` (apiKey, headers, signal) with the entry's `reasoning`
 * applied on top.
 */
export function fallbackStreamFn(base: StreamFn, models: ResolvedModel[], hooks?: FallbackHooks): StreamFn {
    if (models.length === 0) {
        throw new Error('fallbackStreamFn requires at least one model')
    }
    return (_model, context, options) => {
        const out = createAssistantMessageEventStream()
        void (async () => {
            for (let i = 0; i < models.length; i++) {
                const entry = models[i]
                const last = i === models.length - 1
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
                            hooks?.onAttempt?.(i, entry.model)
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
                        hooks?.onAttempt?.(i, entry.model)
                        for (const b of buffered) {
                            out.push(b)
                        }
                        out.end(result)
                        return
                    }
                    if (!last && result.stopReason === 'error' && isFallbackEligible(result.errorMessage)) {
                        hooks?.onFallback?.(i, entry.model, result.errorMessage)
                        continue
                    }
                    // Permanent / abort / exhausted: surface this failure downstream.
                    hooks?.onAttempt?.(i, entry.model)
                    for (const b of buffered) {
                        out.push(b)
                    }
                    out.end(result)
                    return
                } catch (err) {
                    // The contract says base must not throw; defensively treat a
                    // throw as a pre-commit failure (we never forwarded anything,
                    // so we can still fall over). Once committed, re-raise.
                    if (committed) {
                        throw err
                    }
                    const reason = err instanceof Error ? err.message : String(err)
                    if (!last && isFallbackEligible(reason)) {
                        hooks?.onFallback?.(i, entry.model, reason)
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
                    hooks?.onAttempt?.(i, entry.model)
                    out.push({ type: 'error', reason: 'error', error: message })
                    out.end(message)
                    return
                }
            }
        })()
        return out as AssistantMessageEventStream
    }
}
