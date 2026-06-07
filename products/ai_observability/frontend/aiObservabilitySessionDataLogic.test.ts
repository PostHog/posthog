import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sceneLogic } from 'scenes/sceneLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import {
    AnyResponseType,
    DataTableNode,
    LLMTrace,
    LLMTraceEvent,
    NodeKind,
    TracesQuery,
} from '~/queries/schema/schema-general'
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

const traceEvent = (
    traceId: string,
    id: string,
    overrides: { event?: string; createdAt?: string; properties?: Record<string, any> } = {}
): LLMTraceEvent => ({
    id,
    event: overrides.event ?? '$ai_generation',
    createdAt: overrides.createdAt ?? '2026-05-01T00:00:00.000Z',
    properties: { $ai_trace_id: traceId, ...overrides.properties },
})

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

    it('loadAllSessionEvents calls SessionMessagesQuery with sessionId and groups events by trace_id', async () => {
        const traces = [traceSummary('trace-1'), traceSummary('trace-2'), traceSummary('trace-3')]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        // The runner returns a flat list of LLMTraceEvent objects with heavy
        // AI props already merged into `properties` server-side. The frontend
        // only groups by `properties.$ai_trace_id`.
        mockApi.query.mockResolvedValue({
            results: [
                traceEvent('trace-1', 'evt-1a', { properties: { $ai_input: 'a' } }),
                traceEvent('trace-1', 'evt-1b', {
                    event: '$ai_span',
                    createdAt: '2026-05-01T00:00:00.500Z',
                    properties: { $ai_span_name: 'lookup' },
                }),
                traceEvent('trace-2', 'evt-2a', {
                    createdAt: '2026-05-01T00:00:01.000Z',
                    properties: { $ai_input: 'b' },
                }),
                traceEvent('trace-3', 'evt-3a', {
                    createdAt: '2026-05-01T00:00:02.000Z',
                    properties: { $ai_input: 'c' },
                }),
            ],
        } as any)

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        expect(mockApi.query).toHaveBeenCalledWith(
            expect.objectContaining({ kind: NodeKind.SessionMessagesQuery, sessionId: SESSION_ID })
        )
        expect(Object.keys(logic.values.fullTraces).sort()).toEqual(['trace-1', 'trace-2', 'trace-3'])
        expect(logic.values.fullTraces['trace-1'].events).toHaveLength(2)
        expect(logic.values.fullTraces['trace-1'].events.map((e) => e.id)).toEqual(['evt-1a', 'evt-1b'])
        // Heavy properties pass through unchanged — server side already merged them.
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
            results: [traceEvent('trace-1', 'evt-1')],
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

    it('loadAllSessionEvents skips events with no $ai_trace_id', async () => {
        const traces = [traceSummary('trace-1')]
        const props = buildProps({ cachedResults: buildCachedResults(traces) })
        logic = aiObservabilitySessionDataLogic(props)
        logic.mount()

        mockApi.query.mockResolvedValue({
            results: [
                traceEvent('trace-1', 'evt-good'),
                // Session-scoped event with no trace_id should be ignored client-side
                // (also filtered server-side, but defensive).
                {
                    id: 'evt-orphan',
                    event: '$ai_metric',
                    createdAt: '2026-05-01T00:00:01.000Z',
                    properties: {},
                } as LLMTraceEvent,
            ],
        } as any)

        await expectLogic(logic, () => {
            logic.actions.loadAllSessionEvents()
        }).toFinishAllListeners()

        const events = logic.values.fullTraces['trace-1'].events
        expect(events).toHaveLength(1)
        expect(events[0].id).toBe('evt-good')
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
            results: [traceEvent('trace-1', 'evt-1')],
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
