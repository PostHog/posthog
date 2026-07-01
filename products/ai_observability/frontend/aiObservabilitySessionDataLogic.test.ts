import api from 'lib/api'

import { LLMTrace, NodeKind, SessionMessagesQuery, TraceQuery } from '~/queries/schema/schema-general'
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

    function traceQueryCalls(): TraceQuery[] {
        return querySpy.mock.calls
            .map(([query]) => query)
            .filter((query): query is TraceQuery => query?.kind === NodeKind.TraceQuery)
    }

    function sessionMessagesQueryCalls(): SessionMessagesQuery[] {
        return querySpy.mock.calls
            .map(([query]) => query)
            .filter((query): query is SessionMessagesQuery => query?.kind === NodeKind.SessionMessagesQuery)
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

    it('bulk-loads every trace’s events in a single query and skips per-trace fetches', async () => {
        querySpy.mockImplementation((query) =>
            Promise.resolve({
                results:
                    query?.kind === NodeKind.SessionMessagesQuery
                        ? [
                              {
                                  id: 'e1',
                                  event: '$ai_generation',
                                  createdAt: '2026-01-01T00:00:01Z',
                                  properties: { $ai_trace_id: 'trace-a' },
                              },
                              {
                                  id: 'e2',
                                  event: '$ai_span',
                                  createdAt: '2026-01-01T00:00:02Z',
                                  properties: { $ai_trace_id: 'trace-b' },
                              },
                          ]
                        : [],
            } as any)
        )

        // Remount with a populated trace list so the `traces` subscription fires the bulk load.
        logic.unmount()
        logic = aiObservabilitySessionDataLogic({
            sessionId: 'session-1',
            query: sessionLogic.values.query,
            cachedResults: {
                results: [
                    { id: 'trace-a', createdAt: '2026-01-01T00:00:00Z', events: [] },
                    { id: 'trace-b', createdAt: '2026-01-01T00:00:00Z', events: [] },
                ],
            } as any,
        })
        logic.mount()
        await settleListeners()

        // One bulk query for the whole session, and no per-trace TraceQuery on the happy path.
        expect(sessionMessagesQueryCalls()).toHaveLength(1)
        expect(sessionMessagesQueryCalls()[0].sessionId).toBe('session-1')
        expect(traceQueryCalls()).toHaveLength(0)
        // Each trace is populated with the events grouped by `$ai_trace_id`.
        expect(logic.values.fullTraces['trace-a']?.events).toHaveLength(1)
        expect(logic.values.fullTraces['trace-b']?.events).toHaveLength(1)
        expect(logic.values.initialBulkLoaded).toBe(true)
    })
})
