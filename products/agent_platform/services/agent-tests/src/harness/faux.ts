/**
 * Test-side helpers for scripting agent behavior via pi-ai's `faux` provider.
 *
 * pi-ai ships a faux provider in `@earendil-works/pi-ai/faux` — calling
 * `registerFauxProvider()` registers a synthetic provider that any pi-ai
 * `complete()`/`stream()` call resolves through. Scripts are arrays of
 * `AssistantMessage` (or factories) returned one-per-call.
 *
 * The harness wires the runner with a faux Model via resolveModel — the
 * driver streams through pi-ai's `streamSimple`, which resolves the faux
 * provider, so the real code path runs with no in-process mocks.
 */

import type { AssistantMessage, Model, ToolCall } from '@earendil-works/pi-ai'
import { fauxAssistantMessage, fauxToolCall, registerFauxProvider } from '@earendil-works/pi-ai'

export interface FauxAgentScript {
    /** Logical name for the model id (becomes "faux/<name>"). */
    name: string
    /** Scripted responses, one per turn. Cycles back to the start if exhausted. */
    turns: ScriptedTurn[]
}

export type ScriptedTurn = AssistantMessage | TurnBuilder
export type TurnBuilder = () => AssistantMessage

let registered = false

/** Register the faux provider once per process and return its handle. */
export function ensureFauxProvider(): ReturnType<typeof registerFauxProvider> {
    if (!registered) {
        const handle = registerFauxProvider({
            api: 'faux',
            provider: 'faux',
            models: [{ id: 'faux' }],
        })
        registered = true
        ;(globalThis as Record<string, unknown>).__fauxHandle = handle
    }
    return (globalThis as Record<string, unknown>).__fauxHandle as ReturnType<typeof registerFauxProvider>
}

/**
 * Build a faux pi-ai `Model` and arm it with a script. Subsequent
 * `complete(model, ...)` calls walk the script.
 */
export function buildFauxModel(script: ScriptedTurn[]): Model<'faux'> {
    const handle = ensureFauxProvider()
    handle.setResponses(script.map((t) => (typeof t === 'function' ? () => t() : t)))
    return handle.getModel() as Model<'faux'>
}

/* ---------------- Builders for common response shapes ---------------- */

export function fauxText(text: string): AssistantMessage {
    return fauxAssistantMessage(text, { stopReason: 'stop' })
}

export function fauxStaticText(text: string): AssistantMessage {
    return fauxAssistantMessage(text, { stopReason: 'stop' })
}

export function fauxNoop(): AssistantMessage {
    return fauxAssistantMessage('', { stopReason: 'stop' })
}

export function fauxToolUse(calls: ToolCall[]): AssistantMessage {
    return fauxAssistantMessage(calls, { stopReason: 'toolUse' })
}

/** Single-tool helper — calls one tool with the given args. */
export function fauxCallTool(name: string, args: Record<string, unknown> = {}): AssistantMessage {
    return fauxToolUse([fauxToolCall(name, args)])
}

export function fauxErrorTurn(message: string): AssistantMessage {
    return fauxAssistantMessage('', { stopReason: 'error', errorMessage: message })
}

export function fauxLengthCapped(): AssistantMessage {
    return fauxAssistantMessage('(cut off)', { stopReason: 'length' })
}
