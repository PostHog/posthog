import api from 'lib/api'

import { LLMTrace, NodeKind, TraceQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { aiObservabilitySessionDataLogic } from './aiObservabilitySessionDataLogic'
import { aiObservabilitySessionLogic } from './aiObservabilitySessionLogic'

describe('aiObservabilitySessionDataLogic', () => {
    let sessionLogic: ReturnType<typeof aiObservabilitySessionLogic.build>
    let logic: ReturnType<typeof aiObservabilitySessionDataLogic.build>
    let querySpy: jest.SpyInstance

    async function settleListeners(): Promise<void> {
        for (let i = 0; i < 5; i++) {
            await Promise.resolve()
        }
    }

    function traceWithEvents(events: LLMTrace['events'] = []): LLMTrace {
        return {
            id: 'trace-1',
            createdAt: '2026-01-01T00:00:00Z',
            events,
        } as LLMTrace
    }

    function traceWithId(id: string): LLMTrace {
        return { ...traceWithEvents(), id }
    }

    function traceQueryCalls(): TraceQuery[] {
        return querySpy.mock.calls
            .map(([query]) => query)
            .filter((query): query is TraceQuery => query?.kind === NodeKind.TraceQuery)
    }

    beforeEach(() => {
        initKeaTests()
        querySpy = jest.spyOn(api, 'query').mockResolvedValue({ results: [traceWithEvents()] } as any)
        sessionLogic = aiObservabilitySessionLogic()
        sessionLogic.mount()
        sessionLogic.actions.setSessionId('session-1')
        sessionLogic.actions.setDateRange('-7d', null)
        logic = aiObservabilitySessionDataLogic({
            sessionId: 'session-1',
            query: sessionLogic.values.query,
            cachedResults: { results: [] } as any,
        })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        sessionLogic.unmount()
        jest.restoreAllMocks()
    })

    it('refetches full trace details after the date range changes', async () => {
        logic.actions.loadFullTrace('trace-1')
        await settleListeners()
        expect(traceQueryCalls()).toHaveLength(1)
        expect(traceQueryCalls()[0].dateRange?.date_from).toBe('-7d')

        logic.actions.loadFullTrace('trace-1')
        await settleListeners()
        expect(traceQueryCalls()).toHaveLength(1)

        sessionLogic.actions.setDateRange('-24h', null)
        await settleListeners()
        logic.actions.loadFullTrace('trace-1')
        await settleListeners()

        expect(traceQueryCalls()).toHaveLength(2)
        expect(traceQueryCalls()[1].dateRange?.date_from).toBe('-24h')
    })

    it('expands the first trace event when opening the drawer without a focus target', async () => {
        querySpy.mockImplementation((query) => {
            return Promise.resolve({
                results:
                    query?.kind === NodeKind.TraceQuery
                        ? [
                              traceWithEvents([
                                  { id: 'second-event', event: '$ai_span', createdAt: '2026-01-01T00:00:02Z' },
                                  { id: 'first-event', event: '$ai_generation', createdAt: '2026-01-01T00:00:01Z' },
                              ] as LLMTrace['events']),
                          ]
                        : [],
            } as any)
        })

        logic.actions.openStepsDrawer('trace-1')
        await settleListeners()

        expect(logic.values.expandedGenerationIds).toEqual(new Set(['first-event']))
    })

    it('extends the loaded prefix in bounded batches and gates concurrent batches', async () => {
        // Re-mount on a session with more traces than the initial eager window.
        logic.unmount()
        const traces = Array.from({ length: 12 }, (_, i) => traceWithId(`trace-${i}`))
        logic = aiObservabilitySessionDataLogic({
            sessionId: 'session-1',
            query: sessionLogic.values.query,
            cachedResults: { results: traces } as any,
        })
        logic.mount()
        await settleListeners()

        // Initial eager load fires exactly the first batch; more turns remain.
        expect(traceQueryCalls()).toHaveLength(5)
        expect(logic.values.hasMoreTurns).toBe(true)

        // One batch extends the prefix by 5 (5 -> 10). A second call while that batch
        // is still in flight must not fire more queries — this is the concurrency gate.
        logic.actions.loadMoreTurns()
        logic.actions.loadMoreTurns()
        expect(traceQueryCalls()).toHaveLength(10)

        await settleListeners()

        // Final batch loads the remaining 2 (10 -> 12); then nothing is left to load.
        logic.actions.loadMoreTurns()
        await settleListeners()
        expect(traceQueryCalls()).toHaveLength(12)
        expect(logic.values.hasMoreTurns).toBe(false)
    })
})
