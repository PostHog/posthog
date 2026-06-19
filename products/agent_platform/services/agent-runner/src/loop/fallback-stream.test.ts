import type { StreamFn } from '@earendil-works/pi-agent-core'
import {
    type AssistantMessage,
    type AssistantMessageEvent,
    createAssistantMessageEventStream,
    type Model,
} from '@earendil-works/pi-ai'
import { describe, expect, it, vi } from 'vitest'

import { fallbackStreamFn, isFallbackEligible, type ResolvedModel } from './fallback-stream'

function fakeModel(id: string): Model<string> {
    return {
        id,
        name: id,
        api: 'faux',
        provider: 'faux',
        baseUrl: 'http://localhost:0',
        reasoning: false,
        input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 1000,
        maxTokens: 1000,
    } as unknown as Model<string>
}

function msg(over: Partial<AssistantMessage> = {}): AssistantMessage {
    return {
        role: 'assistant',
        content: [],
        api: 'faux',
        provider: 'faux',
        model: 'm',
        usage: {
            input: 0,
            output: 0,
            cacheRead: 0,
            cacheWrite: 0,
            totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        stopReason: 'stop',
        timestamp: 0,
        ...over,
    } as AssistantMessage
}

/** A base StreamFn that emits the given event sequence then ends with `result`. */
function scriptedBase(
    byModelId: Record<string, { events: AssistantMessageEvent[]; result: AssistantMessage }>
): StreamFn {
    return (model) => {
        const stream = createAssistantMessageEventStream()
        const script = byModelId[model.id]
        queueMicrotask(() => {
            for (const e of script.events) {
                stream.push(e)
            }
            stream.end(script.result)
        })
        return stream
    }
}

/** Drive a stream the way the loop does: collect events + the final result. */
async function drive(
    stream: ReturnType<StreamFn>
): Promise<{ events: AssistantMessageEvent[]; result: AssistantMessage }> {
    const s = await stream
    const events: AssistantMessageEvent[] = []
    for await (const e of s) {
        events.push(e)
    }
    return { events, result: await s.result() }
}

const success = (text: string): { events: AssistantMessageEvent[]; result: AssistantMessage } => {
    const partial = msg({ content: [{ type: 'text', text }] })
    return {
        events: [
            { type: 'start', partial: msg() },
            { type: 'text_start', contentIndex: 0, partial },
            { type: 'text_delta', contentIndex: 0, delta: text, partial },
            { type: 'done', reason: 'stop', message: partial },
        ],
        result: partial,
    }
}

/** Pre-commit error: `start` then `error` with empty content (faux-style). */
const preCommitError = (reason: string): { events: AssistantMessageEvent[]; result: AssistantMessage } => {
    const errored = msg({ stopReason: 'error', errorMessage: reason })
    return {
        events: [
            { type: 'start', partial: msg() },
            { type: 'error', reason: 'error', error: errored },
        ],
        result: errored,
    }
}

describe('isFallbackEligible', () => {
    it.each([
        ['429 Too Many Requests', true],
        ['rate limit exceeded', true],
        ['ECONNRESET', true],
        ['socket hang up', true],
        ['503 upstream', true],
        ['quota exceeded', true],
        ['400 bad request', false],
        ['401 unauthorized', false],
        ['403 forbidden', false],
        ['some random validation failure', false],
        [undefined, false],
    ])('%s -> %s', (reason, expected) => {
        expect(isFallbackEligible(reason as string | undefined)).toBe(expected)
    })
})

describe('fallbackStreamFn', () => {
    const models = (ids: string[]): ResolvedModel[] => ids.map((id) => ({ model: fakeModel(id) }))

    it('uses the primary model when it succeeds (no fallover)', async () => {
        const base = scriptedBase({ a: success('hi'), b: success('unused') })
        const onFallback = vi.fn()
        const fn = fallbackStreamFn(base, models(['a', 'b']), { onFallback })
        const { result } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
        expect(result.stopReason).toBe('stop')
        expect(onFallback).not.toHaveBeenCalled()
    })

    it('falls over to the next model on a transient pre-commit failure', async () => {
        const base = scriptedBase({ a: preCommitError('429 rate limit'), b: success('recovered') })
        const onAttempt = vi.fn()
        const onFallback = vi.fn()
        const fn = fallbackStreamFn(base, models(['a', 'b']), { onAttempt, onFallback })
        const { result, events } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
        expect(result.stopReason).toBe('stop')
        expect(result.content).toEqual([{ type: 'text', text: 'recovered' }])
        // The first model's pre-commit `start`/`error` must NOT leak downstream.
        expect(events.some((e) => e.type === 'error')).toBe(false)
        expect(onFallback).toHaveBeenCalledTimes(1)
        expect(onFallback).toHaveBeenCalledWith(0, expect.objectContaining({ id: 'a' }), '429 rate limit')
        expect(onAttempt).toHaveBeenCalledWith(1, expect.objectContaining({ id: 'b' }))
    })

    it('does NOT fall over on a permanent client error — surfaces it from the primary', async () => {
        const base = scriptedBase({ a: preCommitError('400 bad request'), b: success('never') })
        const onFallback = vi.fn()
        const fn = fallbackStreamFn(base, models(['a', 'b']), { onFallback })
        const { result } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
        expect(result.stopReason).toBe('error')
        expect(result.errorMessage).toBe('400 bad request')
        expect(onFallback).not.toHaveBeenCalled()
    })

    it('surfaces the last error when every model fails transiently (attempt cap = list length)', async () => {
        const calls: string[] = []
        const base: StreamFn = (model) => {
            calls.push(model.id)
            return scriptedBase({
                a: preCommitError('429 a'),
                b: preCommitError('503 b'),
            })(model, { messages: [] } as never, undefined)
        }
        const fn = fallbackStreamFn(base, models(['a', 'b']))
        const { result } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
        expect(result.stopReason).toBe('error')
        expect(result.errorMessage).toBe('503 b')
        // Exactly the list length — no extra attempts.
        expect(calls).toEqual(['a', 'b'])
    })

    it('cannot fall over once committed — a mid-stream error stays on the committed model', async () => {
        // Model `a` commits (emits content) then fails. We must NOT retry `b`.
        const partial = msg({ content: [{ type: 'text', text: 'partial' }] })
        const committedThenError: { events: AssistantMessageEvent[]; result: AssistantMessage } = {
            events: [
                { type: 'start', partial: msg() },
                { type: 'text_delta', contentIndex: 0, delta: 'partial', partial },
                { type: 'error', reason: 'error', error: msg({ stopReason: 'error', errorMessage: '503 mid' }) },
            ],
            result: msg({ stopReason: 'error', errorMessage: '503 mid' }),
        }
        const base = scriptedBase({ a: committedThenError, b: success('should not run') })
        const onFallback = vi.fn()
        const fn = fallbackStreamFn(base, models(['a', 'b']), { onFallback })
        const { result, events } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
        expect(result.stopReason).toBe('error')
        expect(result.errorMessage).toBe('503 mid')
        // The committed content WAS forwarded downstream.
        expect(events.some((e) => e.type === 'text_delta')).toBe(true)
        expect(onFallback).not.toHaveBeenCalled()
    })

    it('applies each entry per-entry reasoning on its attempt', async () => {
        const seen: Array<string | undefined> = []
        const base: StreamFn = (model, _ctx, opts) => {
            seen.push(opts?.reasoning)
            return scriptedBase({ a: preCommitError('429'), b: success('ok') })(model, { messages: [] } as never, opts)
        }
        const list: ResolvedModel[] = [
            { model: fakeModel('a'), reasoning: 'low' },
            { model: fakeModel('b'), reasoning: 'high' },
        ]
        const fn = fallbackStreamFn(base, list)
        await drive(fn(fakeModel('a'), { messages: [] } as never, { reasoning: 'medium' } as never))
        expect(seen).toEqual(['low', 'high'])
    })
})
