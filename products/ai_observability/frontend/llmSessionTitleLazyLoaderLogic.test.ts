import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { llmSessionTitleLazyLoaderLogic } from './llmSessionTitleLazyLoaderLogic'

// A row as the loader's queries return it: [session_id, input_state, gen_input, trace_name].
type Row = [string, unknown, unknown, unknown]

function userInputState(text: string): string {
    return JSON.stringify({ messages: [{ role: 'user', content: text }] })
}

// A date bound is required for the loader to query the shared `events` table.
const DATE_RANGE = { dateFrom: '-30d', dateTo: null }

// Let the listener's setTimeout(0) batch timer fire, then drain the api.query +
// merge microtask chain (allSettled → map → fetchSessionTitles → allSettled).
async function settle(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0))
    for (let i = 0; i < 10; i++) {
        await Promise.resolve()
    }
}

describe('llmSessionTitleLazyLoaderLogic', () => {
    let logic: ReturnType<typeof llmSessionTitleLazyLoaderLogic.build>

    // Resolve api.query per source: `posthog.ai_events` rows vs shared `events` rows.
    function mockSources(opts: { events?: Row[] | Error; aiEvents?: Row[] | Error }): void {
        jest.spyOn(api, 'query').mockImplementation((node: any) => {
            const q: string = node?.query ?? ''
            const source = q.includes('posthog.ai_events') ? opts.aiEvents : opts.events
            if (source instanceof Error) {
                return Promise.reject(source)
            }
            return Promise.resolve({ results: source ?? [] } as any)
        })
    }

    beforeEach(() => {
        initKeaTests()
        logic = llmSessionTitleLazyLoaderLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    describe('state', () => {
        it('getSessionTitle is undefined before a session is requested', () => {
            expect(logic.values.getSessionTitle('s1')).toBeUndefined()
        })

        it('stores resolved titles and clears loading on batch success', async () => {
            await expectStored(() => logic.actions.loadSessionTitlesBatchSuccess(new Map([['s1', 'hello']]), ['s1']))
            expect(logic.values.getSessionTitle('s1')).toBe('hello')
            expect(logic.values.loadingSessionIds.has('s1')).toBe(false)
        })

        it('stores null (not undefined) for a requested session with no resolved title', async () => {
            await expectStored(() => logic.actions.loadSessionTitlesBatchSuccess(new Map(), ['s1']))
            expect(logic.values.getSessionTitle('s1')).toBeNull()
        })

        it('stores null on batch failure', async () => {
            await expectStored(() => logic.actions.loadSessionTitlesBatchFailure(['s1']))
            expect(logic.values.getSessionTitle('s1')).toBeNull()
        })

        async function expectStored(run: () => void): Promise<void> {
            run()
            await Promise.resolve()
        }
    })

    describe('fetchSessionTitles merge', () => {
        it('resolves the title from the opening user message', async () => {
            mockSources({ events: [['s1', userInputState('plan a trip to Japan'), '', '']] })
            logic.actions.ensureSessionTitleLoaded('s1', DATE_RANGE)
            await settle()
            expect(logic.values.getSessionTitle('s1')).toBe('plan a trip to Japan')
        })

        it('handles a session id that collides with object prototype keys without polluting Object.prototype', async () => {
            mockSources({ events: [['__proto__', userInputState('not prototype pollution'), '', '']] })
            logic.actions.ensureSessionTitleLoaded('__proto__', DATE_RANGE)
            await settle()
            expect(logic.values.getSessionTitle('__proto__')).toBe('not prototype pollution')
            // The merge must not have written the parsed payload onto Object.prototype.
            expect(({} as Record<string, unknown>).inputState).toBeUndefined()
        })

        it('merges payloads split across the events and ai_events tables', async () => {
            // Flipped team: the message lives in ai_events, the trace name on events.
            // Both must merge, and the real user message must win.
            mockSources({
                events: [['s1', '', '', 'my-trace-name']],
                aiEvents: [['s1', userInputState('what changed in the funnel?'), '', '']],
            })
            logic.actions.ensureSessionTitleLoaded('s1', DATE_RANGE)
            await settle()
            expect(logic.values.getSessionTitle('s1')).toBe('what changed in the funnel?')
        })

        it('falls back to the trace name from the events source when there is no user message', async () => {
            mockSources({ events: [['s1', '', '', 'switch-project']] })
            logic.actions.ensureSessionTitleLoaded('s1', DATE_RANGE)
            await settle()
            expect(logic.values.getSessionTitle('s1')).toBe('switch-project')
        })

        it('falls back to the trace name from the ai_events source', async () => {
            mockSources({ aiEvents: [['s1', '', '', 'ingest-workflow']] })
            logic.actions.ensureSessionTitleLoaded('s1')
            await settle()
            expect(logic.values.getSessionTitle('s1')).toBe('ingest-workflow')
        })

        it('rejects a generic framework trace name (no usable title → null)', async () => {
            mockSources({ events: [['s1', '', '', 'LangGraph']] })
            logic.actions.ensureSessionTitleLoaded('s1', DATE_RANGE)
            await settle()
            expect(logic.values.getSessionTitle('s1')).toBeNull()
        })

        it('tolerates one source failing and resolves from the other (allSettled)', async () => {
            mockSources({
                events: new Error('events table query failed'),
                aiEvents: [['s1', userInputState('still works'), '', '']],
            })
            logic.actions.ensureSessionTitleLoaded('s1', DATE_RANGE)
            await settle()
            expect(logic.values.getSessionTitle('s1')).toBe('still works')
        })

        it('marks the batch failed (null) when every source query fails', async () => {
            jest.spyOn(console, 'warn').mockImplementation(() => {}) // the loader warns on total failure
            mockSources({ events: new Error('boom'), aiEvents: new Error('boom') })
            logic.actions.ensureSessionTitleLoaded('s1', DATE_RANGE)
            await settle()
            expect(logic.values.getSessionTitle('s1')).toBeNull()
        })

        it('resolves titles for multiple sessions in one batch', async () => {
            mockSources({
                events: [
                    ['s1', userInputState('first session'), '', ''],
                    ['s2', '', '', 'named-trace'],
                ],
            })
            logic.actions.ensureSessionTitleLoaded('s1', DATE_RANGE)
            logic.actions.ensureSessionTitleLoaded('s2', DATE_RANGE)
            await settle()
            expect(logic.values.getSessionTitle('s1')).toBe('first session')
            expect(logic.values.getSessionTitle('s2')).toBe('named-trace')
        })
    })

    describe('date range bound', () => {
        it('applies the passed date range to the events query, leaving ai_events TTL-bounded', async () => {
            const queried: any[] = []
            jest.spyOn(api, 'query').mockImplementation((node: any) => {
                queried.push(node)
                return Promise.resolve({ results: [] } as any)
            })

            logic.actions.ensureSessionTitleLoaded('s1', { dateFrom: '-7d', dateTo: null })
            await settle()

            const eventsNode = queried.find((n) => typeof n?.query === 'string' && n.query.includes('FROM events'))
            const aiEventsNode = queried.find(
                (n) => typeof n?.query === 'string' && n.query.includes('posthog.ai_events')
            )

            // events query is time-bounded via the shared {filters} idiom
            expect(eventsNode?.query).toContain('{filters}')
            expect(eventsNode?.filters?.dateRange?.date_from).toBe('-7d')
            // ai_events is bounded by its TTL, not a date filter
            expect(aiEventsNode?.query).not.toContain('{filters}')
            expect(aiEventsNode?.filters).toBeUndefined()
        })

        it('does NOT query the unbounded events table when no date range is passed', async () => {
            const queried: any[] = []
            jest.spyOn(api, 'query').mockImplementation((node: any) => {
                queried.push(node)
                return Promise.resolve({ results: [] } as any)
            })

            logic.actions.ensureSessionTitleLoaded('s1')
            await settle()

            const eventsNode = queried.find((n) => typeof n?.query === 'string' && n.query.includes('FROM events'))
            const aiEventsNode = queried.find(
                (n) => typeof n?.query === 'string' && n.query.includes('posthog.ai_events')
            )
            expect(eventsNode).toBeUndefined() // conservative: events table skipped without a bound
            expect(aiEventsNode).not.toBeUndefined() // ai_events (TTL-bounded) still runs
        })
    })

    describe('field truncation', () => {
        it('truncates fields with character-aware substringUTF8 in both source queries, never byte-based substring', async () => {
            const queried: any[] = []
            jest.spyOn(api, 'query').mockImplementation((node: any) => {
                queried.push(node)
                return Promise.resolve({ results: [] } as any)
            })

            logic.actions.ensureSessionTitleLoaded('s1', DATE_RANGE)
            await settle()

            const eventsNode = queried.find((n) => typeof n?.query === 'string' && n.query.includes('FROM events'))
            const aiEventsNode = queried.find(
                (n) => typeof n?.query === 'string' && n.query.includes('posthog.ai_events')
            )

            expect(eventsNode?.query).toContain('substringUTF8(')
            expect(eventsNode?.query).not.toContain('substring(')
            expect(aiEventsNode?.query).toContain('substringUTF8(')
            expect(aiEventsNode?.query).not.toContain('substring(')
        })
    })
})
