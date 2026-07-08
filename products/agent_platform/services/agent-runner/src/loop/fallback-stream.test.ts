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

    // The contract says `base` shouldn't throw, but the wrapper defends against
    // it (a throw before commit is indistinguishable from a pre-commit failure).
    it('falls over when the base THROWS an eligible error before committing', async () => {
        const base: StreamFn = (model) => {
            if (model.id === 'a') {
                throw new Error('503 boom')
            }
            return scriptedBase({ b: success('recovered') })(model, { messages: [] } as never, undefined)
        }
        const onFallback = vi.fn()
        const fn = fallbackStreamFn(base, models(['a', 'b']), { onFallback })
        const { result } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
        expect(result.stopReason).toBe('stop')
        expect(result.content).toEqual([{ type: 'text', text: 'recovered' }])
        expect(onFallback).toHaveBeenCalledWith(0, expect.objectContaining({ id: 'a' }), '503 boom')
    })

    it('synthesizes an error message when the base THROWS a non-eligible error (no fallover)', async () => {
        const calls: string[] = []
        const base: StreamFn = (model) => {
            calls.push(model.id)
            throw new Error('400 nope')
        }
        const onFallback = vi.fn()
        const fn = fallbackStreamFn(base, models(['a', 'b']), { onFallback })
        const { result } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
        expect(result.stopReason).toBe('error')
        expect(result.errorMessage).toBe('400 nope')
        // Permanent → surfaced from the primary, second model never tried.
        expect(calls).toEqual(['a'])
        expect(onFallback).not.toHaveBeenCalled()
    })

    describe('session stickiness (optimize_for)', () => {
        // A base that records which models were tried per turn and routes its
        // response per (turn, model id). `turn.n` is bumped between drives.
        function turnRoutedBase(
            tried: string[][],
            turn: { n: number },
            respond: (turn: number, id: string) => { events: AssistantMessageEvent[]; result: AssistantMessage }
        ): StreamFn {
            return (model) => {
                if (!tried[turn.n]) {
                    tried[turn.n] = []
                }
                tried[turn.n].push(model.id)
                const script = respond(turn.n, model.id)
                const stream = createAssistantMessageEventStream()
                queueMicrotask(() => {
                    for (const e of script.events) {
                        stream.push(e)
                    }
                    stream.end(script.result)
                })
                return stream
            }
        }

        const drive2 = (fn: StreamFn): ReturnType<typeof drive> =>
            drive(fn(fakeModel('a'), { messages: [] } as never, undefined))

        it('cost (default): pins the first served model — later turns never try the others', async () => {
            const tried: string[][] = []
            const turn = { n: 0 }
            // turn 0: a fails transiently → b serves and becomes the pin.
            const base = turnRoutedBase(tried, turn, (t, id) =>
                t === 0 && id === 'a' ? preCommitError('429') : success(id)
            )
            const fn = fallbackStreamFn(base, models(['a', 'b'])) // optimize_for defaults to cost
            await drive2(fn)
            turn.n = 1
            await drive2(fn)
            turn.n = 2
            await drive2(fn)
            expect(tried[0]).toEqual(['a', 'b']) // turn 0 walked a → b
            expect(tried[1]).toEqual(['b']) // pinned to b — a is never tried again
            expect(tried[2]).toEqual(['b'])
        })

        it('cost: a pinned model failing does NOT fall over — it surfaces the error', async () => {
            const tried: string[][] = []
            const turn = { n: 0 }
            const base = turnRoutedBase(tried, turn, (t, id) => {
                if (t === 0 && id === 'a') {
                    return preCommitError('429') // establish pin = b
                }
                if (t === 1 && id === 'b') {
                    return preCommitError('503') // pinned model now fails
                }
                return success(id)
            })
            const fn = fallbackStreamFn(base, models(['a', 'b']))
            await drive2(fn)
            turn.n = 1
            const { result } = await drive2(fn)
            // Cost mode is pinned to b: it must NOT fall back to the (healthy) a.
            expect(tried[1]).toEqual(['b'])
            expect(result.stopReason).toBe('error')
            expect(result.errorMessage).toBe('503')
        })

        it('availability: leads with the sticky model but falls over when it fails, then re-sticks', async () => {
            const tried: string[][] = []
            const turn = { n: 0 }
            const base = turnRoutedBase(tried, turn, (t, id) => {
                if (t === 0 && id === 'a') {
                    return preCommitError('429') // establish served = b
                }
                if (t === 1 && id === 'b') {
                    return preCommitError('503') // sticky b fails → fall over to a
                }
                return success(id)
            })
            const fn = fallbackStreamFn(base, models(['a', 'b']), undefined, { optimizeFor: 'availability' })
            await drive2(fn) // turn 0: a → b
            turn.n = 1
            const turn1 = await drive2(fn) // turn 1: lead b, b fails, fall over to a
            expect(tried[1]).toEqual(['b', 'a'])
            expect(turn1.result.content).toEqual([{ type: 'text', text: 'a' }])
            turn.n = 2
            await drive2(fn) // turn 2: re-stuck to the survivor a
            expect(tried[2]).toEqual(['a'])
        })

        it('seeds the pin from initialServedId so it survives a resume (cost)', async () => {
            const tried: string[][] = []
            const turn = { n: 0 }
            const base = turnRoutedBase(tried, turn, (_t, id) => success(id))
            const fn = fallbackStreamFn(base, models(['a', 'b']), undefined, { initialServedId: 'b' })
            await drive2(fn)
            // First turn after resume is already pinned to the resumed model.
            expect(tried[0]).toEqual(['b'])
        })

        it('reports the ORIGINAL policy index for a sticky non-primary lead', async () => {
            const onAttempt = vi.fn()
            const base = scriptedBase({ a: success('a'), b: success('b') })
            const fn = fallbackStreamFn(
                base,
                models(['a', 'b']),
                { onAttempt },
                {
                    optimizeFor: 'availability',
                    initialServedId: 'b',
                }
            )
            await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
            // b leads, but its policy index (1) is what analytics records.
            expect(onAttempt).toHaveBeenCalledWith(1, expect.objectContaining({ id: 'b' }))
        })

        it('cost: pins the PRIMARY when it serves first, and still will not fall over if it later fails', async () => {
            // The common case: the primary is healthy on turn 0, so cost pins it
            // and never even considers the fallback — including on a later failure.
            const tried: string[][] = []
            const turn = { n: 0 }
            const base = turnRoutedBase(tried, turn, (t, id) =>
                t === 1 && id === 'a' ? preCommitError('503') : success(id)
            )
            const fn = fallbackStreamFn(base, models(['a', 'b'])) // cost default
            await drive2(fn) // turn 0: primary a serves → pin = a (b never tried)
            turn.n = 1
            const { result } = await drive2(fn) // turn 1: a fails; cost must NOT try b
            expect(tried[0]).toEqual(['a'])
            expect(tried[1]).toEqual(['a'])
            expect(result.stopReason).toBe('error')
        })

        it('availability: a stuck MIDDLE model leads, then the rest follow in ORIGINAL priority order', async () => {
            // 3 models a,b,c with served=b. Order must be [b, a, c]: sticky lead
            // first, then the remaining models in priority order (a before c) —
            // exercises the reorder beyond the trivial 2-model case. b and a fail
            // so the whole fall-through order is observable.
            const tried: string[][] = []
            const turn = { n: 0 }
            const base = turnRoutedBase(tried, turn, (_t, id) => (id === 'c' ? success(id) : preCommitError('503')))
            const fn = fallbackStreamFn(base, models(['a', 'b', 'c']), undefined, {
                optimizeFor: 'availability',
                initialServedId: 'b',
            })
            const { result } = await drive2(fn)
            expect(tried[0]).toEqual(['b', 'a', 'c'])
            expect(result.content).toEqual([{ type: 'text', text: 'c' }])
        })

        it('ignores a stale initialServedId no longer in the list and walks from the primary', async () => {
            // e.g. the pinned model was dropped from the policy between runs.
            const tried: string[][] = []
            const turn = { n: 0 }
            const base = turnRoutedBase(tried, turn, (_t, id) => success(id))
            const fn = fallbackStreamFn(base, models(['a', 'b']), undefined, { initialServedId: 'ghost' })
            await drive2(fn)
            expect(tried[0]).toEqual(['a'])
        })

        it('fires onPinLost when the seeded sticky model is no longer in the list', async () => {
            // The pin loss must surface — otherwise a delisted model silently
            // costs the session its prompt-cache warmth, only visible
            // indirectly as a lower hit-rate downstream.
            const onPinLost = vi.fn()
            const base = scriptedBase({ a: success('a'), b: success('b') })
            const fn = fallbackStreamFn(base, models(['a', 'b']), { onPinLost }, { initialServedId: 'ghost' })
            await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
            expect(onPinLost).toHaveBeenCalledWith('ghost')
        })

        it('does not fire onPinLost when the seeded sticky model is still in the list', async () => {
            const onPinLost = vi.fn()
            const base = scriptedBase({ a: success('a'), b: success('b') })
            const fn = fallbackStreamFn(base, models(['a', 'b']), { onPinLost }, { initialServedId: 'b' })
            await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
            expect(onPinLost).not.toHaveBeenCalled()
        })
    })

    describe('IIFE error guard', () => {
        // The wrapper runs its dispatch loop in a detached async IIFE so the
        // returned stream is available synchronously. Any path that lets that
        // promise reject without ending the stream would hang callers awaiting
        // `.result()`. These tests pin the guarantee.

        it('ends the stream when `stream.result()` rejects AFTER the first content event (post-commit)', async () => {
            // Once we've forwarded an event downstream, we can't fall over —
            // but we also can't let the rejection float. The guard must surface
            // the failure as a stop=error result rather than leaving `.result()`
            // pending forever (which is what the pre-fix `void (async ...)`
            // would have done).
            const base: StreamFn = () => {
                // A hand-rolled stream whose iterator yields one content event
                // then ends, but whose `result()` rejects — exercises the
                // `if (committed) throw err` re-raise path. Built by hand
                // (not via createAssistantMessageEventStream) so we have full
                // control over the rejection without depending on its API.
                async function* iter(): AsyncGenerator<AssistantMessageEvent> {
                    yield {
                        type: 'text_delta',
                        contentIndex: 0,
                        delta: 'hello',
                        partial: msg({ content: [{ type: 'text', text: 'hello' }] }),
                    } as AssistantMessageEvent
                }
                const gen = iter()
                return {
                    [Symbol.asyncIterator]: () => gen,
                    result: () => Promise.reject(new Error('mid-stream provider crash')),
                } as unknown as ReturnType<StreamFn>
            }
            const fn = fallbackStreamFn(base, models(['a']))
            // Must resolve, not hang. If the guard regresses, this test
            // times out under vitest's default test timeout.
            const { result } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
            expect(result.stopReason).toBe('error')
            expect(result.errorMessage).toMatch(/mid-stream/)
        })

        it('ends the stream when `base` throws synchronously on the FIRST attempt with no fallback eligible', async () => {
            // Defensive guard for the no-throw contract being violated by a bug
            // (not a network error). Must surface as an error result with no fallover.
            const base: StreamFn = () => {
                throw new Error('exploded')
            }
            const fn = fallbackStreamFn(base, models(['a']))
            const { result } = await drive(fn(fakeModel('a'), { messages: [] } as never, undefined))
            expect(result.stopReason).toBe('error')
            expect(result.errorMessage).toBe('exploded')
        })
    })
})
