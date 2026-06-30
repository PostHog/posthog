import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { traceMessagesLazyLoaderLogic } from './traceMessagesLazyLoaderLogic'

// A row as the loader's query returns it:
// [trace_id, last_input, last_output, last_input_fallback, last_output_fallback].
type Row = [string, unknown, unknown, unknown, unknown]

const CREATED_AT = '2026-04-11T19:20:55.828Z'

function messages(...msgs: { role: string; content: string }[]): string {
    return JSON.stringify(msgs)
}

// Let the listener's setTimeout(0) batch timer fire, then drain the api.query +
// merge microtask chain (allSettled → map → loadTraceMessagesBatchSuccess).
async function settle(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0))
    for (let i = 0; i < 10; i++) {
        await Promise.resolve()
    }
}

describe('traceMessagesLazyLoaderLogic', () => {
    let logic: ReturnType<typeof traceMessagesLazyLoaderLogic.build>

    function mockQuery(rows: Row[] | Error): void {
        jest.spyOn(api, 'query').mockImplementation(() => {
            if (rows instanceof Error) {
                return Promise.reject(rows)
            }
            return Promise.resolve({ results: rows } as any)
        })
    }

    beforeEach(() => {
        initKeaTests()
        logic = traceMessagesLazyLoaderLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    describe('generation fallback query', () => {
        it('sources the input fallback from the latest generation (argMaxIf), not the first', async () => {
            const queried: any[] = []
            jest.spyOn(api, 'query').mockImplementation((node: any) => {
                queried.push(node)
                return Promise.resolve({ results: [] } as any)
            })

            logic.actions.ensureTraceMessagesLoaded([{ id: 't1', createdAt: CREATED_AT }])
            await settle()

            const query: string = queried[0]?.query ?? ''
            // The reviewer's bug: argMinIf picked the conversation's opening turn.
            // The fallback must use the most recent generation instead.
            expect(query).toContain('argMaxIf(')
            expect(query).toContain('AS last_input_fallback')
            expect(query).not.toContain('argMinIf(')
        })
    })

    describe('row mapping', () => {
        it('maps the trace-level input/output state and the generation fallbacks', async () => {
            mockQuery([
                [
                    't1',
                    messages({ role: 'user', content: 'trace input' }),
                    messages({ role: 'assistant', content: 'trace output' }),
                    messages({ role: 'user', content: 'gen input' }),
                    messages({ role: 'assistant', content: 'gen output' }),
                ],
            ])
            logic.actions.ensureTraceMessagesLoaded([{ id: 't1', createdAt: CREATED_AT }])
            await settle()

            const result = logic.values.getTraceMessages('t1')
            expect(result?.lastInput).toEqual([{ role: 'user', content: 'trace input' }])
            expect(result?.lastOutput).toEqual([{ role: 'assistant', content: 'trace output' }])
            expect(result?.lastInputFallback).toEqual([{ role: 'user', content: 'gen input' }])
            expect(result?.lastOutputFallback).toEqual([{ role: 'assistant', content: 'gen output' }])
        })

        it('exposes the generation fallback when the trace has no $ai_trace input state', async () => {
            // Empty trace-level state (older/backfilled trace) → the consumer falls
            // back to the latest generation's full input.
            mockQuery([
                [
                    't1',
                    '',
                    '',
                    messages(
                        { role: 'user', content: 'first turn' },
                        { role: 'assistant', content: 'answer' },
                        { role: 'user', content: 'latest turn' }
                    ),
                    '',
                ],
            ])
            logic.actions.ensureTraceMessagesLoaded([{ id: 't1', createdAt: CREATED_AT }])
            await settle()

            const result = logic.values.getTraceMessages('t1')
            expect(result?.lastInput).toBeNull()
            expect(result?.lastInputFallback).toEqual([
                { role: 'user', content: 'first turn' },
                { role: 'assistant', content: 'answer' },
                { role: 'user', content: 'latest turn' },
            ])
        })

        it('stores null fields for a requested trace absent from the response', async () => {
            mockQuery([])
            logic.actions.ensureTraceMessagesLoaded([{ id: 't1', createdAt: CREATED_AT }])
            await settle()

            const result = logic.values.getTraceMessages('t1')
            expect(result).toEqual({
                lastInput: null,
                lastOutput: null,
                lastInputFallback: null,
                lastOutputFallback: null,
            })
        })

        it('stores null on query failure', async () => {
            jest.spyOn(console, 'warn').mockImplementation(() => {})
            mockQuery(new Error('boom'))
            logic.actions.ensureTraceMessagesLoaded([{ id: 't1', createdAt: CREATED_AT }])
            await settle()

            expect(logic.values.getTraceMessages('t1')).toBeNull()
        })
    })

    describe('field truncation', () => {
        it('truncates message fields with character-aware substringUTF8, never byte-based substring', async () => {
            const queried: any[] = []
            jest.spyOn(api, 'query').mockImplementation((node: any) => {
                queried.push(node)
                return Promise.resolve({ results: [] } as any)
            })

            logic.actions.ensureTraceMessagesLoaded([{ id: 't1', createdAt: CREATED_AT }])
            await settle()

            const query: string = queried[0]?.query ?? ''
            expect(query).toContain('substringUTF8(')
            expect(query).not.toContain('substring(')
        })
    })
})
