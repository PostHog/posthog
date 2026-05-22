import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { messageSignature } from './messageSignature'
import { CompatMessage } from './types'
import { normalizeMessage, normalizeMessages } from './utils'

// Heuristic mirrors the AI observability skill script `print_summary.py` at
// `products/ai_observability/skills/exploring-llm-traces/scripts/` — keep in sync.

/**
 * Pick the event that represents the user-visible turn for a trace.
 *
 * Current heuristic: the latest `$ai_generation` by `createdAt` — an
 * implementation detail callers should treat as opaque. A future opt-in
 * `$ai_user_visible: true` convention would change how this picks. Wrong
 * for traces where the last generation is a logging/cleanup call; the
 * "Show reasoning" affordance is the user's fallback.
 */
export function pickUserVisibleTurn(trace: LLMTrace | undefined): LLMTraceEvent | undefined {
    if (!trace?.events?.length) {
        return undefined
    }
    let latest: LLMTraceEvent | undefined
    let latestTs = -Infinity
    for (const event of trace.events) {
        if (event.event !== '$ai_generation') {
            continue
        }
        const ts = new Date(event.createdAt).getTime()
        if (ts > latestTs) {
            latest = event
            latestTs = ts
        }
    }
    return latest
}

/**
 * Maps each normalized message back to its index in the raw `$ai_input`.
 * Many-to-one: `normalizeMessage` may expand one raw entry into multiple
 * messages. A leading `-1` marks the synthetic "available tools" message.
 *
 * Used by `ConversationMessagesDisplay` to map per-message sentiment to the
 * right rendered bubble after dedup. Also used by the Trace page renderer.
 */
export function buildInputSourceIndices(rawInput: unknown, tools: unknown): number[] {
    const indices: number[] = []
    if (tools) {
        indices.push(-1)
    }
    if (Array.isArray(rawInput)) {
        for (let i = 0; i < rawInput.length; i++) {
            const expanded = normalizeMessage(rawInput[i], 'user')
            for (let j = 0; j < expanded.length; j++) {
                indices.push(i)
            }
        }
    }
    return indices
}

export interface SessionTurn {
    /** The trace this turn corresponds to. */
    trace: LLMTrace
    /** True if `fullTraces[trace.id]` was available and we computed messages. */
    isLoaded: boolean
    /** Input messages new to this turn (already-seen messages from prior turns hidden). */
    newInputs: CompatMessage[]
    /** Output messages from this turn's last generation. */
    outputs: CompatMessage[]
    /** Maps each `newInputs[i]` back to its source index in the raw `$ai_input` array. */
    newInputSourceIndices: number[]
    /** The event sourced by `pickUserVisibleTurn` — used for model, error, latency, and the id passed to `ConversationMessagesDisplay`. */
    userVisibleTurn?: LLMTraceEvent
}

/**
 * Walk traces in order and hide inputs already shown in an earlier turn.
 * Without this, turn N would re-render turns 1..N-1 because each `$ai_input`
 * carries the full running history.
 *
 * Count-based, not set-based: a message at its Nth occurrence in a turn's
 * input renders iff fewer than N copies have been shown so far. Preserves
 * legitimate repeats within a turn.
 */
export function extractSessionTurns(traces: LLMTrace[], fullTraces: Record<string, LLMTrace>): SessionTurn[] {
    const msgCountShown = new Map<string, number>()
    return traces.map((trace) => {
        const fullTrace = fullTraces[trace.id]
        if (!fullTrace) {
            return {
                trace,
                isLoaded: false,
                newInputs: [],
                outputs: [],
                newInputSourceIndices: [],
            }
        }
        const userVisibleTurn = pickUserVisibleTurn(fullTrace)
        if (!userVisibleTurn) {
            return {
                trace,
                isLoaded: true,
                newInputs: [],
                outputs: [],
                newInputSourceIndices: [],
            }
        }
        const { properties } = userVisibleTurn
        const rawInput = properties.$ai_input ?? properties.$ai_input_state
        const rawOutput = properties.$ai_output_choices ?? properties.$ai_output_state ?? properties.$ai_output
        const tools = properties.$ai_tools

        const inputMessages = normalizeMessages(rawInput, 'user', tools)
        const outputMessages = normalizeMessages(rawOutput, 'assistant')
        const sourceIndices = buildInputSourceIndices(rawInput, tools)

        const newInputs: CompatMessage[] = []
        const newInputSourceIndices: number[] = []
        const msgCountThisTurn = new Map<string, number>()
        inputMessages.forEach((message, i) => {
            const sig = messageSignature(message)
            const turnCount = (msgCountThisTurn.get(sig) ?? 0) + 1
            msgCountThisTurn.set(sig, turnCount)
            const shownCount = msgCountShown.get(sig) ?? 0
            if (turnCount > shownCount) {
                newInputs.push(message)
                newInputSourceIndices.push(sourceIndices[i] ?? i)
                msgCountShown.set(sig, turnCount)
            }
        })
        for (const message of outputMessages) {
            const sig = messageSignature(message)
            msgCountShown.set(sig, (msgCountShown.get(sig) ?? 0) + 1)
        }

        return {
            trace,
            isLoaded: true,
            newInputs,
            outputs: outputMessages,
            newInputSourceIndices,
            userVisibleTurn,
        }
    })
}
