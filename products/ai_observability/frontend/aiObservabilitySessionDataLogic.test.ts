import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import type { LLMTrace, SessionQueryResponse, TraceQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { aiObservabilitySessionDataLogic } from './aiObservabilitySessionDataLogic'
import { aiObservabilitySessionLogic } from './aiObservabilitySessionLogic'
import { llmAnalyticsSummarizationBatchCheckCreate, llmAnalyticsSummarizationCreate } from './generated/api'

jest.mock('./generated/api', () => ({
    ...jest.requireActual('./generated/api'),
    llmAnalyticsSummarizationBatchCheckCreate: jest.fn(),
    llmAnalyticsSummarizationCreate: jest.fn(),
}))

const batchCheckCreate = llmAnalyticsSummarizationBatchCheckCreate as jest.Mock
const summarizationCreate = llmAnalyticsSummarizationCreate as jest.Mock

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
            distinctId: 'person1',
            events,
        }
    }

    function sessionResponse(results: LLMTrace[] = []): SessionQueryResponse {
        return { results }
    }

    function traceQueryCalls(): TraceQuery[] {
        return querySpy.mock.calls
            .map(([query]) => query)
            .filter((query): query is TraceQuery => query?.kind === NodeKind.TraceQuery)
    }

    beforeEach(() => {
        initKeaTests()
        batchCheckCreate.mockReset()
        batchCheckCreate.mockResolvedValue({ summaries: [] })
        summarizationCreate.mockReset()
        querySpy = jest.spyOn(api, 'query').mockResolvedValue(sessionResponse([traceWithEvents()]))
        sessionLogic = aiObservabilitySessionLogic()
        sessionLogic.mount()
        sessionLogic.actions.setSessionId('session-1')
        sessionLogic.actions.setDateRange('-7d', null)
        logic = aiObservabilitySessionDataLogic({
            sessionId: 'session-1',
            query: sessionLogic.values.query,
            cachedResults: sessionResponse(),
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

    it('hydrates full traces from the session response without trace fanout', async () => {
        logic.unmount()
        const trace = traceWithEvents([
            {
                id: 'generation-1',
                event: '$ai_generation',
                createdAt: '2026-01-01T00:00:01Z',
                properties: {
                    $ai_input: [{ role: 'user', content: 'hello' }],
                    $ai_output_choices: [{ role: 'assistant', content: 'hi' }],
                },
            },
        ])
        querySpy.mockClear()

        logic = aiObservabilitySessionDataLogic({
            sessionId: 'session-1',
            query: sessionLogic.values.query,
            cachedResults: sessionResponse([trace]),
        })
        logic.mount()
        await settleListeners()

        expect(traceQueryCalls()).toHaveLength(0)
        expect(logic.values.fullTraces['trace-1']).toEqual(trace)
        expect(logic.values.sessionTurns[0].isLoaded).toBe(true)
    })

    it('expands the first trace event when opening the drawer without a focus target', async () => {
        querySpy.mockImplementation((query) => {
            return Promise.resolve(
                query?.kind === NodeKind.TraceQuery
                    ? sessionResponse([
                          traceWithEvents([
                              {
                                  id: 'second-event',
                                  event: '$ai_span',
                                  createdAt: '2026-01-01T00:00:02Z',
                                  properties: {},
                              },
                              {
                                  id: 'first-event',
                                  event: '$ai_generation',
                                  createdAt: '2026-01-01T00:00:01Z',
                                  properties: {},
                              },
                          ]),
                      ])
                    : sessionResponse()
            )
        })

        logic.actions.openStepsDrawer('trace-1')
        await settleListeners()

        expect(logic.values.expandedGenerationIds).toEqual(new Set(['first-event']))
    })

    it('summarizes a trace by ID instead of posting its contents', async () => {
        summarizationCreate.mockResolvedValue({ summary: { title: 'A short title' }, text_repr: '' })
        logic.actions.loadFullTraceSuccess('trace-1', traceWithEvents(), '-7d\0')

        logic.actions.summarizeTrace('trace-1', false)
        await settleListeners()

        expect(summarizationCreate.mock.calls[0][1]).toEqual({
            mode: 'minimal',
            force_refresh: false,
            trace_id: 'trace-1',
            date_from: '2025-12-31T00:00:00.000Z',
            date_to: '2026-01-02T00:00:00.000Z',
        })
        expect(logic.values.traceSummaries['trace-1'].title).toBe('A short title')
    })
})
