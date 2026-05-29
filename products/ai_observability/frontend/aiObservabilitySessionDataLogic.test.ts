import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sceneLogic } from 'scenes/sceneLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, LLMTrace, NodeKind, TracesQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps } from '~/types'

import { aiObservabilitySessionDataLogic, SessionDataLogicProps } from './aiObservabilitySessionDataLogic'
import { aiObservabilitySessionLogic } from './aiObservabilitySessionLogic'

jest.mock('lib/api')
// The summarization batch-check endpoint fires whenever traces appear via a
// subscription side-effect. Stub it out so it doesn't try to hit a real URL.
jest.mock('./generated/api', () => ({
    llmAnalyticsSummarizationBatchCheckCreate: jest.fn().mockResolvedValue({ summaries: [] }),
}))

const mockApi = api as jest.Mocked<typeof api>

const SESSION_ID = 'test-session-uuid'
const TAB_ID = '1'

const traceSummary = (id: string, extra: Partial<LLMTrace> = {}): LLMTrace =>
    ({
        id,
        createdAt: '2026-05-01T00:00:00.000Z',
        distinctId: 'user-1',
        traceName: `name-${id}`,
        errorCount: 0,
        totalLatency: 1.0,
        events: [],
        ...extra,
    }) as LLMTrace

function buildQuery(): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.TracesQuery,
            properties: [],
        } as TracesQuery,
    }
}

// `traces` selector in the logic reverses `response.results` (the production
// query returns newest-first and the session view wants chronological order).
// Pass the desired chronological traces in reverse so the selector reverses
// them back to the order the test expects.
function buildCachedResults(traces: LLMTrace[]): AnyResponseType {
    return {
        results: [...traces].reverse(),
        columns: [],
        hasMore: false,
        hogql: '',
        timings: [],
        modifiers: {},
    } as unknown as AnyResponseType
}

function buildProps(opts: Partial<SessionDataLogicProps> = {}): SessionDataLogicProps {
    return {
        sessionId: SESSION_ID,
        query: buildQuery(),
        tabId: TAB_ID,
        ...opts,
    }
}

// Helper: get the dataNodeLogic mounted by the session data logic so we can
// directly populate response (mirrors how `cachedResults` flows in production).
function dataNode(props: SessionDataLogicProps): ReturnType<typeof dataNodeLogic.build> {
    const tabScope = props.tabId ?? 'default'
    const scopedSessionId = `${props.sessionId}:${tabScope}`
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Session.${scopedSessionId}`,
        dataNodeCollectionId: scopedSessionId,
    }
    return dataNodeLogic({
        query: props.query.source,
        key: insightVizDataNodeKey(insightProps),
        dataNodeCollectionId: scopedSessionId,
    })
}

const blankScene = (): any => ({ scene: { component: () => null, logic: null } })
const scenes: any = { AIObservabilitySession: blankScene }

describe('aiObservabilitySessionDataLogic — bulk session-events loader', () => {
    let logic: ReturnType<typeof aiObservabilitySessionDataLogic.build>
    let sessionLogic: ReturnType<typeof aiObservabilitySessionLogic.build>

    beforeEach(() => {
        jest.resetAllMocks()
        initKeaTests()
        sceneLogic({ scenes }).mount()
        sceneLogic.actions.setTabs([
            { id: TAB_ID, title: '...', pathname: '/', search: '', hash: '', active: true, iconType: 'blank' },
        ])
        sessionLogic = aiObservabilitySessionLogic({ tabId: TAB_ID })
        sessionLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        sessionLogic.unmount()
    })

    it('loadAllSessionEvents groups flat rows into fullTraces by trace_id', async () => {
        const traces = [traceSummary('trace-1'), traceSummary('trace-2'), traceSummary('trace-3')]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        // Properties arrive as JSON-encoded strings (verified against prod
        // ClickHouse: the `events.properties` column is `String`).
        mockApi.query.mockResolvedValue({
            results: [
                ['trace-1', 'evt-1a', '$ai_generation', '2026-05-01T00:00:00.000Z', '{"$ai_input":"a"}'],
                ['trace-1', 'evt-1b', '$ai_span', '2026-05-01T00:00:00.500Z', '{"$ai_span_name":"lookup"}'],
                ['trace-2', 'evt-2a', '$ai_generation', '2026-05-01T00:00:01.000Z', '{"$ai_input":"b"}'],
                ['trace-3', 'evt-3a', '$ai_generation', '2026-05-01T00:00:02.000Z', '{"$ai_input":"c"}'],
            ],
        } as any)

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        expect(Object.keys(logic.values.fullTraces).sort()).toEqual(['trace-1', 'trace-2', 'trace-3'])
        expect(logic.values.fullTraces['trace-1'].events).toHaveLength(2)
        expect(logic.values.fullTraces['trace-1'].events.map((e) => e.id)).toEqual(['evt-1a', 'evt-1b'])
        // Properties are parsed from the JSON string into an object so the
        // renderer can read `$ai_input` / `$ai_output_choices` directly.
        expect(logic.values.fullTraces['trace-1'].events[0].properties.$ai_input).toBe('a')
        expect(logic.values.fullTraces['trace-2'].events).toHaveLength(1)
        expect(logic.values.fullTraces['trace-3'].events).toHaveLength(1)
    })

    it('loadAllSessionEvents preserves trace summary fields when merging events', async () => {
        const traces = [traceSummary('trace-1', { traceName: 'rich-name', errorCount: 7, totalLatency: 12.34 })]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        mockApi.query.mockResolvedValue({
            results: [['trace-1', 'evt-1', '$ai_generation', '2026-05-01T00:00:00.000Z', '{}']],
        } as any)

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        const stored = logic.values.fullTraces['trace-1']
        expect(stored.traceName).toBe('rich-name')
        expect(stored.errorCount).toBe(7)
        expect(stored.totalLatency).toBe(12.34)
        expect(stored.events).toHaveLength(1)
    })

    it('loadAllSessionEvents tolerates malformed JSON in properties without failing the bulk load', async () => {
        // If one event has corrupt JSON we render that event with empty
        // properties and keep going — the rest of the session must still
        // load. Pinned to guard against a regression where a single bad row
        // would set bulkLoadError and blank the whole UI.
        const traces = [traceSummary('trace-1')]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()
        const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => undefined)

        mockApi.query.mockResolvedValue({
            results: [
                ['trace-1', 'evt-good', '$ai_generation', '2026-05-01T00:00:00.000Z', '{"$ai_input":"ok"}'],
                ['trace-1', 'evt-bad', '$ai_span', '2026-05-01T00:00:00.500Z', '{not valid json'],
            ],
        } as any)

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        expect(logic.values.bulkLoadError).toBeNull()
        const events = logic.values.fullTraces['trace-1'].events
        expect(events).toHaveLength(2)
        expect(events[0].properties.$ai_input).toBe('ok')
        // The corrupt row's properties default to `{}` so downstream code can
        // still iterate them safely.
        expect(events[1].properties).toEqual({})
        expect(consoleWarnSpy).toHaveBeenCalled()
        consoleWarnSpy.mockRestore()
    })

    it('loadAllSessionEvents toggles bulkLoading true then false', async () => {
        const traces = [traceSummary('trace-1')]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        let resolveQuery: (value: any) => void = () => {}
        const pending = new Promise((resolve) => {
            resolveQuery = resolve
        })
        mockApi.query.mockReturnValue(pending as any)

        logic.actions.loadAllSessionEvents()
        expect(logic.values.bulkLoading).toBe(true)

        resolveQuery({ results: [] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.bulkLoading).toBe(false)
    })

    it('loadAllSessionEvents on failure sets bulkLoadError and clears in-flight', async () => {
        const traces = [traceSummary('trace-1'), traceSummary('trace-2')]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        mockApi.query.mockRejectedValueOnce(new Error('clickhouse timeout'))
        // Swallow expected console.error from the listener's catch block.
        const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined)

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        expect(logic.values.bulkLoading).toBe(false)
        expect(logic.values.bulkLoadError).toBe('clickhouse timeout')
        // No fallback path exists — the manual per-trace `loadFullTrace`
        // action was removed in the bulk-loader cleanup. The error banner +
        // retry button at the scene level is the only recovery surface.
        expect(logic.values.fullTraces).toEqual({})

        consoleSpy.mockRestore()
    })

    it('subscription fires loadAllSessionEvents exactly once when traces first appear', async () => {
        // No cachedResults — traces start empty.
        const props = buildProps()
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        const node = dataNode(props)
        const bulkLoadSpy = jest.spyOn(logic.actions, 'loadAllSessionEvents')
        mockApi.query.mockResolvedValue({ results: [] } as any)

        // Inject traces into dataNodeLogic; the `traces` selector recomputes and
        // the subscription fires.
        node.actions.setResponse({
            results: [traceSummary('trace-1')],
        } as any)
        await expectLogic(logic).toFinishAllListeners()

        expect(bulkLoadSpy).toHaveBeenCalledTimes(1)
    })

    it('subscription refires loadAllSessionEvents when pagination appends new unloaded traces', async () => {
        const initial = [traceSummary('trace-1')]
        const props = buildProps({ cachedResults: buildCachedResults(initial) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        mockApi.query.mockResolvedValue({
            results: [['trace-1', 'evt-1', '$ai_generation', '2026-05-01T00:00:00.000Z', '{}']],
        } as any)

        // Drive the initial bulk load explicitly so fullTraces is populated
        // for trace-1; this matches the post-initial-mount state.
        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()
        expect(Object.keys(logic.values.fullTraces)).toContain('trace-1')

        const bulkLoadSpy = jest.spyOn(logic.actions, 'loadAllSessionEvents')

        // Simulate pagination: a NEW trace appears in `traces`. trace-2 has no
        // fullTraces entry yet, so the subscription's `hasUnloadedTrace` guard
        // is true and the bulk loader refires. After it completes, trace-2's
        // conversation bubble renders in place of a "no userVisibleTurn"
        // placeholder.
        const node = dataNode(props)
        node.actions.setResponse({
            results: [traceSummary('trace-1'), traceSummary('trace-2')].reverse(),
        } as any)
        await expectLogic(logic).toFinishAllListeners()

        expect(bulkLoadSpy).toHaveBeenCalledTimes(1)
    })

    it('loadAllSessionEvents merges ai_events heavy columns into properties', async () => {
        // ai_events stores heavy AI payloads in dedicated columns; the listener
        // folds them back into `properties` so consumers see the same shape as
        // backend's `merge_heavy_properties`.
        const traces = [traceSummary('trace-1')]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        mockApi.query.mockResolvedValue({
            results: [
                [
                    'trace-1',
                    'evt-1',
                    '$ai_generation',
                    '2026-05-01T00:00:00.000Z',
                    '{"$ai_model":"gpt-4"}',
                    '[{"role":"user","content":"hi"}]', // input
                    null, // output
                    '[{"message":{"role":"assistant","content":"hello"}}]', // output_choices
                    null, // input_state
                    null, // output_state
                    '[{"name":"search"}]', // tools
                ],
            ],
        } as any)

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        const event = logic.values.fullTraces['trace-1'].events[0]
        // Light props survive untouched.
        expect(event.properties.$ai_model).toBe('gpt-4')
        // Heavy columns are parsed and merged back into properties.
        expect(event.properties.$ai_input).toEqual([{ role: 'user', content: 'hi' }])
        expect(event.properties.$ai_output_choices).toEqual([{ message: { role: 'assistant', content: 'hello' } }])
        expect(event.properties.$ai_tools).toEqual([{ name: 'search' }])
        // Null heavy columns are skipped (no key added with a null value).
        expect(event.properties).not.toHaveProperty('$ai_output')
        expect(event.properties).not.toHaveProperty('$ai_input_state')
        expect(event.properties).not.toHaveProperty('$ai_output_state')
    })

    it('loadAllSessionEvents falls back to events table when ai_events returns no rows', async () => {
        // Sessions older than ai_events' 30-day TTL fall back to the events table.
        const traces = [
            traceSummary('trace-1', { createdAt: '2026-01-15T12:00:00.000Z' }),
            traceSummary('trace-2', { createdAt: '2026-01-15T12:30:00.000Z' }),
        ]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        // The traces subscription auto-fires loadAllSessionEvents in addition to
        // the explicit call below — mockImplementation handles every invocation.
        mockApi.query.mockImplementation((q: any) => {
            if (typeof q?.query === 'string' && q.query.includes('FROM posthog.ai_events')) {
                return Promise.resolve({ results: [] } as any)
            }
            return Promise.resolve({
                results: [
                    [
                        'trace-1',
                        'evt-1',
                        '$ai_generation',
                        '2026-01-15T12:00:00.500Z',
                        // Pre-stripping events still carry the heavy props
                        // inline in `properties` JSON — no separate heavy
                        // columns to merge.
                        '{"$ai_input":"legacy","$ai_output_choices":["legacy reply"]}',
                    ],
                ],
            } as any)
        })

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        const queries = mockApi.query.mock.calls.map((c) => (c[0] as any).query as string)
        const aiEventsCalled = queries.some((q) => q.includes('FROM posthog.ai_events'))
        const eventsCall = mockApi.query.mock.calls.find(
            (c) =>
                typeof (c[0] as any)?.query === 'string' &&
                (c[0] as any).query.includes('FROM events') &&
                !(c[0] as any).query.includes('ai_events')
        )
        expect(aiEventsCalled).toBe(true)
        expect(eventsCall).not.toBeUndefined()
        const eventsQueryNode = eventsCall![0] as any
        expect(eventsQueryNode.query).toContain('timestamp >=')
        expect(eventsQueryNode.query).toContain('timestamp <=')
        // trace_id IN filter narrows post-prune row filtering to just the
        // missing traces — defends against partial-coverage edge cases.
        expect(eventsQueryNode.query).toContain('properties.$ai_trace_id IN {traceIds}')
        expect(eventsQueryNode.values.sessionId).toBe(SESSION_ID)
        expect(eventsQueryNode.values.traceIds).toEqual(['trace-1', 'trace-2'])
        // Both window bounds are populated from trace.createdAt ± buffer.
        expect(typeof eventsQueryNode.values.minTs).toBe('string')
        expect(typeof eventsQueryNode.values.maxTs).toBe('string')
        // Sanity: ai_events is queried first in any given listener invocation.
        expect(queries[0]).toContain('FROM posthog.ai_events')

        const event = logic.values.fullTraces['trace-1'].events[0]
        // Properties came from the events JSON path — no client-side heavy merge
        // applied (those events still carry $ai_input etc. inline today).
        expect(event.properties.$ai_input).toBe('legacy')
        expect(event.properties.$ai_output_choices).toEqual(['legacy reply'])
    })

    it('loadAllSessionEvents fires events fallback for traces missing from ai_events (partial coverage)', async () => {
        // Partial coverage: one old trace in events, one recent trace in ai_events.
        // Both must end up in the merged result.
        const traces = [
            traceSummary('trace-old', { createdAt: '2026-01-15T12:00:00.000Z' }),
            traceSummary('trace-new', { createdAt: '2026-05-20T12:00:00.000Z' }),
        ]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        mockApi.query.mockImplementation((q: any) => {
            if (typeof q?.query === 'string' && q.query.includes('FROM posthog.ai_events')) {
                // Only the recent trace lives in ai_events.
                return Promise.resolve({
                    results: [
                        [
                            'trace-new',
                            'evt-new-1',
                            '$ai_generation',
                            '2026-05-20T12:00:00.500Z',
                            '{"$ai_model":"gpt-4"}',
                            '[{"role":"user","content":"recent"}]',
                            null,
                            null,
                            null,
                            null,
                            null,
                        ],
                    ],
                } as any)
            }
            // Events fallback returns the old trace's row.
            return Promise.resolve({
                results: [
                    [
                        'trace-old',
                        'evt-old-1',
                        '$ai_generation',
                        '2026-01-15T12:00:00.500Z',
                        '{"$ai_input":"legacy","$ai_output_choices":["legacy reply"]}',
                    ],
                ],
            } as any)
        })

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        // Both sources merged into a single fullTraces map.
        expect(logic.values.fullTraces['trace-new'].events).toHaveLength(1)
        expect(logic.values.fullTraces['trace-new'].events[0].id).toBe('evt-new-1')
        expect(logic.values.fullTraces['trace-new'].events[0].properties.$ai_input).toEqual([
            { role: 'user', content: 'recent' },
        ])
        expect(logic.values.fullTraces['trace-old'].events).toHaveLength(1)
        expect(logic.values.fullTraces['trace-old'].events[0].id).toBe('evt-old-1')
        expect(logic.values.fullTraces['trace-old'].events[0].properties.$ai_input).toBe('legacy')

        // The fallback window is scoped to the missing trace only.
        const eventsCall = mockApi.query.mock.calls.find(
            (c) =>
                typeof (c[0] as any)?.query === 'string' &&
                (c[0] as any).query.includes('FROM events') &&
                !(c[0] as any).query.includes('ai_events')
        )
        expect(eventsCall).not.toBeUndefined()
        const eventsQueryNode = eventsCall![0] as any
        const minTs = new Date(eventsQueryNode.values.minTs).getTime()
        const maxTs = new Date(eventsQueryNode.values.maxTs).getTime()
        const oldTraceTs = new Date('2026-01-15T12:00:00.000Z').getTime()
        const recentTraceTs = new Date('2026-05-20T12:00:00.000Z').getTime()
        expect(minTs).toBeLessThan(oldTraceTs)
        expect(maxTs).toBeGreaterThan(oldTraceTs)
        // Critical: the window does NOT span the recent trace — that one is
        // already covered by ai_events and we don't want to re-scan it on events.
        expect(maxTs).toBeLessThan(recentTraceTs)
        expect(eventsQueryNode.values.traceIds).toEqual(['trace-old'])
    })

    it('loadAllSessionEvents skips the events fallback when ai_events covered every trace', async () => {
        // Full coverage from ai_events → no fallback round-trip.
        const traces = [
            traceSummary('trace-1', { createdAt: '2026-05-20T12:00:00.000Z' }),
            traceSummary('trace-2', { createdAt: '2026-05-20T12:30:00.000Z' }),
        ]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        const rows = [
            [
                'trace-1',
                'evt-1',
                '$ai_generation',
                '2026-05-20T12:00:00.500Z',
                '{}',
                null,
                null,
                null,
                null,
                null,
                null,
            ],
            [
                'trace-2',
                'evt-2',
                '$ai_generation',
                '2026-05-20T12:30:00.500Z',
                '{}',
                null,
                null,
                null,
                null,
                null,
                null,
            ],
        ]
        mockApi.query.mockImplementation((q: any) => {
            if (typeof q?.query === 'string' && q.query.includes('FROM posthog.ai_events')) {
                return Promise.resolve({ results: rows } as any)
            }
            // If the events fallback fires here, the test below catches it.
            return Promise.resolve({ results: [] } as any)
        })

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        const eventsCall = mockApi.query.mock.calls.find(
            (c) =>
                typeof (c[0] as any)?.query === 'string' &&
                (c[0] as any).query.includes('FROM events') &&
                !(c[0] as any).query.includes('ai_events')
        )
        expect(eventsCall).toBeUndefined()
    })

    it('refires loadAllSessionEvents when pagination adds traces during an in-flight load', async () => {
        // Pagination lands between the first invocation's two awaits; the new
        // trace must end up loaded, not stuck with empty events.
        const initial = [traceSummary('trace-1')]

        let resolveAiEvents: (value: any) => void = () => {}
        const aiEventsPending = new Promise((resolve) => {
            resolveAiEvents = resolve
        })
        let resolveFallback: (value: any) => void = () => {}
        const fallbackPending = new Promise((resolve) => {
            resolveFallback = resolve
        })

        mockApi.query
            .mockReturnValueOnce(aiEventsPending as any)
            .mockReturnValueOnce(fallbackPending as any)
            // Refire's ai_events covers both traces.
            .mockResolvedValueOnce({
                results: [
                    ['trace-1', 'evt-1', '$ai_generation', '2026-05-01T00:00:00.000Z', '{}'],
                    ['trace-2', 'evt-2', '$ai_generation', '2026-05-01T00:00:00.000Z', '{}'],
                ],
            } as any)

        const props = buildProps({ cachedResults: buildCachedResults(initial) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        // Empty ai_events → fallback runs, giving us a second await to interleave on.
        resolveAiEvents({ results: [] })
        await new Promise((r) => setTimeout(r, 0))

        const node = dataNode(props)
        node.actions.setResponse({
            results: [traceSummary('trace-1'), traceSummary('trace-2')].reverse(),
        } as any)

        resolveFallback({
            results: [['trace-1', 'evt-1', '$ai_generation', '2026-05-01T00:00:00.000Z', '{}']],
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.fullTraces['trace-1'].events).toHaveLength(1)
        expect(logic.values.fullTraces['trace-2'].events).toHaveLength(1)
    })

    it('loadAllSessionEvents handles empty results without erroring', async () => {
        const traces = [traceSummary('trace-1'), traceSummary('trace-2')]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        mockApi.query.mockResolvedValue({ results: [] } as any)

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        // Every trace summary gets a fullTraces entry with an empty events array —
        // the conversation bubbles render as placeholders, the steps panel
        // shows no events, nothing crashes.
        expect(logic.values.fullTraces['trace-1'].events).toEqual([])
        expect(logic.values.fullTraces['trace-2'].events).toEqual([])
        expect(logic.values.bulkLoadError).toBeNull()
        expect(logic.values.bulkLoading).toBe(false)
    })
})
