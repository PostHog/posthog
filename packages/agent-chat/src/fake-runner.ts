/**
 * `<FakeRunnerController />` companion — a tiny in-process runner that
 * plays scripted turns over time.
 *
 * **This is throwaway scaffolding.** It exists so the dock has something
 * to push against before the real runner + client-fulfilled tools
 * protocol lands (v0.2 / v0.3 in
 * [`agent-console-website.md`](docs/agent-platform/plans/agent-console-website.md)).
 * When the real protocol arrives, this controller gets replaced by an
 * SSE-driven `RunnerClient` that consumes `text/thinking/toolcall`
 * delta events from `/listen` — the rendered session shape is the same,
 * so the dock won't move.
 *
 * What it does:
 *   1. Holds a current `ChatSession` and exposes it via a React hook.
 *   2. On `send(text)`, matches the text against a script library and
 *      replays the script's steps over time:
 *      - text chunks stream char-by-char
 *      - tool calls "fire", optionally pause, then "complete" with a
 *        result baked into the script
 *      - `kind: "client"` tool calls invoke a matching registered
 *        handler and bake its return value as the result
 *   3. Surfaces a `clientToolCall` callback so consumers can drive
 *      side effects (page navigation in our case) when client tools
 *      fire — without baking them into the chat package.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AssistantTurnPart, ChatSession, ClientToolHandler, Turn } from './types'

/* ── Script shape ────────────────────────────────────────────────── */

export type ScriptStep =
    | { kind: 'thinking'; text: string }
    | { kind: 'text'; text: string; chunkMs?: number }
    | {
          kind: 'tool_call'
          toolId: string
          fulfillment: 'server' | 'client'
          args: Record<string, unknown>
          /** For server tool calls, the baked result. Client calls invoke the registered handler. */
          result?: { ok: true; body: unknown } | { ok: false; error: string }
          /** Delay before the result resolves (server) or before invoking the handler (client). */
          pendingMs?: number
      }
    | { kind: 'pause'; ms: number }

export interface Script {
    /** Stable id, used in stories + tests. */
    id: string
    /** Used both for matching against incoming user text and as a label. */
    match: (text: string) => boolean
    steps: ScriptStep[]
}

/* ── Controller hook ─────────────────────────────────────────────── */

export interface UseFakeRunnerOpts {
    /** Initial session state — typically the waiting (no-turns) fixture. */
    initialSession: ChatSession
    /** Script library, searched top-to-bottom. First match wins. */
    scripts: Script[]
    /** Fallback played when no script matches. */
    fallbackScript?: Script
    /** Registered handlers — invoked when a `tool_call` step has `fulfillment: 'client'`. */
    handlers?: ClientToolHandler[]
}

export interface FakeRunnerControls {
    session: ChatSession
    /** Send a user message. If a script matches, play it. Ignored while a script is playing. */
    send: (text: string) => void
    /** Reset to the initial session and stop any in-flight playback. */
    reset: () => void
    /** True while a script is currently playing. */
    playing: boolean
}

export function useFakeRunner({
    initialSession,
    scripts,
    fallbackScript,
    handlers = [],
}: UseFakeRunnerOpts): FakeRunnerControls {
    const [session, setSession] = useState<ChatSession>(initialSession)
    const [playing, setPlaying] = useState(false)
    const aliveRef = useRef(true)
    const handlersRef = useRef(handlers)
    handlersRef.current = handlers

    useEffect(() => {
        aliveRef.current = true
        return () => {
            aliveRef.current = false
        }
    }, [])

    const reset = useCallback(() => {
        setSession(initialSession)
        setPlaying(false)
    }, [initialSession])

    const send = useCallback(
        (text: string) => {
            if (!aliveRef.current) {
                return
            }
            const script = scripts.find((s) => s.match(text)) ?? fallbackScript
            const userId = `user-${Date.now()}`
            const assistantId = `assistant-${Date.now()}`

            // Append the user turn + a fresh empty assistant turn we'll grow into.
            setSession((s) => ({
                ...s,
                state: 'streaming',
                turns: [
                    ...s.turns,
                    { kind: 'user', id: userId, timestamp: new Date().toISOString(), text },
                    {
                        kind: 'assistant',
                        id: assistantId,
                        timestamp: new Date().toISOString(),
                        streaming: true,
                        parts: [],
                    },
                ],
            }))

            if (!script) {
                // No script + no fallback — end the turn quietly.
                setSession((s) => finalizeTurn(s, assistantId))
                return
            }

            setPlaying(true)
            void playScript({ script, assistantId, setSession, aliveRef, handlersRef }).finally(() => {
                if (aliveRef.current) {
                    setPlaying(false)
                }
            })
        },
        [scripts, fallbackScript]
    )

    return useMemo(() => ({ session, send, reset, playing }), [session, send, reset, playing])
}

/* ── Player implementation ───────────────────────────────────────── */

async function playScript({
    script,
    assistantId,
    setSession,
    aliveRef,
    handlersRef,
}: {
    script: Script
    assistantId: string
    setSession: React.Dispatch<React.SetStateAction<ChatSession>>
    aliveRef: React.RefObject<boolean>
    handlersRef: React.RefObject<ClientToolHandler[]>
}): Promise<void> {
    for (const step of script.steps) {
        if (!aliveRef.current) {
            return
        }

        if (step.kind === 'pause') {
            await sleep(step.ms)
            continue
        }

        if (step.kind === 'thinking') {
            appendPart(setSession, assistantId, { kind: 'thinking', text: step.text })
            await sleep(250)
            continue
        }

        if (step.kind === 'text') {
            const chunkMs = step.chunkMs ?? 18
            // Append an empty text part we'll grow.
            const partIndex = await appendPartAndGetIndex(setSession, assistantId, { kind: 'text', text: '' })
            for (let i = 0; i < step.text.length; i++) {
                if (!aliveRef.current) {
                    return
                }
                const sliced = step.text.slice(0, i + 1)
                updatePart(setSession, assistantId, partIndex, { kind: 'text', text: sliced })
                await sleep(chunkMs)
            }
            continue
        }

        if (step.kind === 'tool_call') {
            const callId = `call-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
            // Append the call in "pending" state (no result yet).
            const partIndex = await appendPartAndGetIndex(setSession, assistantId, {
                kind: 'tool_call',
                toolId: step.toolId,
                callId,
                fulfillment: step.fulfillment,
                args: step.args,
            })

            await sleep(step.pendingMs ?? 350)
            if (!aliveRef.current) {
                return
            }

            let result: { ok: true; body: unknown } | { ok: false; error: string }

            if (step.fulfillment === 'client') {
                const handler = handlersRef.current?.find((h) => h.id === step.toolId)
                if (handler && 'handle' in handler) {
                    try {
                        const body = await handler.handle(step.args)
                        result = { ok: true, body }
                    } catch (err) {
                        result = { ok: false, error: err instanceof Error ? err.message : String(err) }
                    }
                } else if (handler) {
                    // Render-style handler — the fake runner can't drive
                    // a user-facing UI from a script, so we synthesize
                    // an explanatory result instead. Scripts that need a
                    // specific outcome should provide `step.result`.
                    result = step.result ?? { ok: true, body: { note: 'render-style handler skipped in fake-runner' } }
                } else {
                    result = { ok: false, error: `no client handler registered for ${step.toolId}` }
                }
            } else {
                result =
                    step.result ?? { ok: true, body: { note: 'no result provided in script — synthesized empty body' } }
            }

            updatePart(setSession, assistantId, partIndex, {
                kind: 'tool_call',
                toolId: step.toolId,
                callId,
                fulfillment: step.fulfillment,
                args: step.args,
                result,
            })
            continue
        }
    }

    // Done — clear the streaming flag and bump session to idle.
    if (aliveRef.current) {
        setSession((s) => finalizeTurn(s, assistantId))
    }
}

/* ── Session mutation helpers ────────────────────────────────────── */

function finalizeTurn(session: ChatSession, assistantId: string): ChatSession {
    return {
        ...session,
        state: 'idle',
        turns: session.turns.map((t) =>
            t.kind === 'assistant' && t.id === assistantId ? { ...t, streaming: false } : t
        ),
    }
}

function withAssistantTurn(
    session: ChatSession,
    assistantId: string,
    transform: (parts: AssistantTurnPart[]) => AssistantTurnPart[]
): ChatSession {
    return {
        ...session,
        turns: session.turns.map<Turn>((t) =>
            t.kind === 'assistant' && t.id === assistantId ? { ...t, parts: transform(t.parts) } : t
        ),
    }
}

function appendPart(
    setSession: React.Dispatch<React.SetStateAction<ChatSession>>,
    assistantId: string,
    part: AssistantTurnPart
): void {
    setSession((s) => withAssistantTurn(s, assistantId, (parts) => [...parts, part]))
}

/**
 * Append + return the index of the newly appended part. Used for text
 * chunking and tool-call result baking — both need to mutate the part
 * we just added, repeatedly.
 *
 * Returns a promise because `setState` is async; we need the index
 * after the state has been updated to use it for subsequent updates.
 */
function appendPartAndGetIndex(
    setSession: React.Dispatch<React.SetStateAction<ChatSession>>,
    assistantId: string,
    part: AssistantTurnPart
): Promise<number> {
    return new Promise((resolve) => {
        setSession((s) => {
            const turn = s.turns.find((t) => t.kind === 'assistant' && t.id === assistantId)
            const nextIndex = turn && turn.kind === 'assistant' ? turn.parts.length : 0
            queueMicrotask(() => resolve(nextIndex))
            return withAssistantTurn(s, assistantId, (parts) => [...parts, part])
        })
    })
}

function updatePart(
    setSession: React.Dispatch<React.SetStateAction<ChatSession>>,
    assistantId: string,
    index: number,
    part: AssistantTurnPart
): void {
    setSession((s) =>
        withAssistantTurn(s, assistantId, (parts) => parts.map((p, i) => (i === index ? part : p)))
    )
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}
