import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import type { TraceApi, TraceEvaluationResultsApi } from '../../generated/api.schemas'
import {
    decodeIdSegment,
    makeEvaluationResults,
    makeFeedback,
    makeFeedbackScore,
    makeMessage,
    makeNodeDetail,
    makeRawNode,
    makeTraceCluster,
    makeTraceResource,
} from './testFixtures'
import { traceClustersLogic } from './traceClustersLogic'
import { traceSummaryLogic } from './traceSummaryLogic'
import { traceViewHostLogic } from './traceViewHostLogic'
import { traceViewModelLogic } from './traceViewModelLogic'
import type { TraceOpeningMode } from './types'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/'
const RAW_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/raw/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const CLUSTERS_URL = '/api/projects/:team_id/ai_observability/traces/:id/clusters/'
const CREATED_AT = '2026-09-01T10:15:00Z'
const FEEDBACK_URL = '/api/projects/:team_id/ai_observability/traces/:id/feedback/'
const SEARCH_URL = '/api/projects/:team_id/ai_observability/traces/:id/search/'
const SUMMARY_URL = '/api/projects/:team_id/ai_observability/traces/:id/summary/'
const HOST_ID = 'test-host'

const answeredGeneration = makeNodeDetail({
    id: 'gen-2',
    content: {
        input: {
            kind: 'messages',
            messages: [
                makeMessage({
                    id: 'gen-2-in-0',
                    role: 'user',
                    parts: [{ kind: 'text', text: 'Why did my invoice go up?' }],
                }),
            ],
        },
        output: {
            kind: 'messages',
            messages: [
                makeMessage({
                    id: 'gen-2-out-0',
                    role: 'assistant',
                    parts: [{ kind: 'text', text: 'Two seats were added.' }],
                }),
            ],
        },
    },
})

interface HostState {
    requestedStepId?: string
    openingMode?: TraceOpeningMode
    seedQuery?: string
}

const FEEDBACK = makeFeedback({
    steps: [
        { nodeId: 'gen-1', scores: [makeFeedbackScore()], responseCount: 0, total: 1 },
        { nodeId: 'trace-1', scores: [], responseCount: 1, total: 1 },
    ],
})

describe('traceViewModelLogic', () => {
    let logic: ReturnType<typeof traceViewModelLogic.build>
    let host: ReturnType<typeof traceViewHostLogic.build>
    let traceResource: TraceApi
    let traceGate: Promise<void>
    let nodeRequests: string[]
    let rawRequests: string[]
    let failingRawNodeId: string | null
    let failingNodeId: string | null
    let clusterRequests: string[]
    let clustersStatus: number
    let feedbackStatus: number
    let searchStatus: number
    let summaryRequests: number
    let evaluations: TraceEvaluationResultsApi

    function mountAt({ requestedStepId, openingMode, seedQuery }: HostState = {}): void {
        host = traceViewHostLogic({ hostId: HOST_ID })
        host.mount()
        host.actions.requestStep(requestedStepId ?? null, null)
        host.actions.setOpeningMode(openingMode ?? null)
        host.actions.setSeedQuery(seedQuery ?? '')
        logic = traceViewModelLogic({ hostId: HOST_ID, traceId: 'trace-1', timestampHint: null })
        logic.mount()
    }

    function stepTo(traceId: string): void {
        const previous = logic
        logic = traceViewModelLogic({ hostId: HOST_ID, traceId, timestampHint: null })
        logic.mount()
        previous.unmount()
    }

    beforeEach(() => {
        traceResource = makeTraceResource({ nodeIdsByAlias: { 'sdk-gen-1': 'gen-1' } })
        traceGate = Promise.resolve()
        nodeRequests = []
        rawRequests = []
        failingRawNodeId = null
        failingNodeId = null
        clusterRequests = []
        clustersStatus = 200
        feedbackStatus = 200
        searchStatus = 200
        summaryRequests = 0
        evaluations = makeEvaluationResults()
        useMocks({
            post: {
                [SUMMARY_URL]: () => {
                    summaryRequests += 1
                    return [202, { status: 'pending', content: null, failure: null }]
                },
            },
            get: {
                [SUMMARY_URL]: () => [404, { detail: 'No summary yet.' }],
                [TRACE_URL]: async () => {
                    await traceGate
                    return [200, traceResource]
                },
                [EVALUATIONS_URL]: () => [200, evaluations],
                [CLUSTERS_URL]: ({ request }) => {
                    clusterRequests.push(String(new URL(request.url).searchParams.get('created_at')))
                    return clustersStatus === 200
                        ? [200, { clusters: [makeTraceCluster()] }]
                        : [clustersStatus, { detail: 'Server error.' }]
                },
                [FEEDBACK_URL]: () =>
                    feedbackStatus === 200 ? [200, FEEDBACK] : [feedbackStatus, { detail: 'Server error.' }],
                [SEARCH_URL]: () =>
                    searchStatus === 200
                        ? [
                              200,
                              {
                                  total: 3,
                                  matches: [
                                      { nodeId: 'gen-1', count: 2 },
                                      { nodeId: 'gen-2', count: 1 },
                                  ],
                              },
                          ]
                        : [searchStatus, { detail: 'Search timed out.' }],
                [RAW_URL]: ({ params }) => {
                    const nodeId = decodeIdSegment(String(params.node_id))
                    rawRequests.push(nodeId)
                    if (nodeId === failingRawNodeId) {
                        failingRawNodeId = null
                        return [500, { detail: 'Server error.' }]
                    }
                    return [200, makeRawNode({ id: nodeId })]
                },
                [NODE_URL]: ({ params }) => {
                    const nodeId = decodeIdSegment(String(params.node_id))
                    nodeRequests.push(nodeId)
                    if (nodeId === failingNodeId) {
                        failingNodeId = null
                        return [500, { detail: 'Server error.' }]
                    }
                    if (nodeId === 'gen-2') {
                        return [200, answeredGeneration]
                    }
                    const known = ['trace-1', 'trace-2', 'span-1', 'gen-1'].includes(nodeId)
                    return known ? [200, makeNodeDetail({ id: nodeId })] : [404, { detail: 'Node not found.' }]
                },
            },
        })
        initKeaTests()
        jest.mocked(performQuery).mockReset()
        jest.mocked(performQuery).mockResolvedValue({ results: [] })
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic.unmount()
        host.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('reads a deep-linked node alongside the trace, then the thread node, and never runs the legacy trace query', async () => {
        let releaseTrace = (): void => {}
        traceGate = new Promise<void>((resolve) => {
            releaseTrace = resolve
        })
        mountAt({ requestedStepId: 'span-1' })

        await waitFor(() => expect(nodeRequests).toEqual(['span-1']))
        expect(logic.values.status).toBe('loading')

        releaseTrace()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready', selectedNodeId: 'span-1' })

        expect(nodeRequests).toEqual(['span-1', 'gen-2'])
        expect(jest.mocked(performQuery).mock.calls.some(([query]) => query.kind === 'TraceQuery')).toBe(false)
    })

    it.each([
        ['a node in the tree', { requestedStepId: 'span-1' }, 'span-1'],
        ['an SDK id through its alias', { requestedStepId: 'sdk-gen-1' }, 'gen-1'],
        ['a stale id as the root', { requestedStepId: 'missing' }, 'trace-1'],
        ['a stale id named like an object member as the root', { requestedStepId: 'constructor' }, 'trace-1'],
        ['the trace itself as the root, not the default node', { requestedStepId: 'trace-1' }, 'trace-1'],
        ['no id as the default node', {}, 'gen-1'],
        ['a trace-level link as the root', { openingMode: 'summary' }, 'trace-1'],
    ] as const)('selects %s', async (_name, state: HostState, expected) => {
        traceResource = makeTraceResource({ defaultNodeId: 'gen-1', nodeIdsByAlias: { 'sdk-gen-1': 'gen-1' } })
        mountAt(state)

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ selectedNodeId: expected })
        expect(logic.values.selectedNodeLoad.status).not.toBe('error')
    })

    it('reads no root node for a step requested for the next trace', async () => {
        mountAt({ requestedStepId: 'span-1' })
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready', selectedNodeId: 'span-1' })
        nodeRequests.length = 0

        host.actions.requestStep('next-trace-step', 'trace-2')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedNodeId).toBe('trace-1')
        expect(nodeRequests).toEqual([])
    })

    it('does not read the next trace step under this trace while this trace loads', async () => {
        let releaseTrace = (): void => {}
        traceGate = new Promise<void>((resolve) => {
            releaseTrace = resolve
        })
        mountAt()

        host.actions.requestStep('next-trace-step', 'trace-2')
        releaseTrace()
        await expectLogic(logic).toFinishAllListeners()

        expect(nodeRequests).not.toContain('next-trace-step')
    })

    it('asks for the clusters with the trace start once the trace arrives', async () => {
        let releaseTrace = (): void => {}
        traceGate = new Promise<void>((resolve) => {
            releaseTrace = resolve
        })
        mountAt()

        expect(clusterRequests).toEqual([])
        expect(traceClustersLogic({ traceId: 'trace-1' }).values.clusters).toBeNull()

        releaseTrace()
        await expectLogic(logic).toFinishAllListeners()

        expect(clusterRequests).toEqual([CREATED_AT])
        expect(traceClustersLogic({ traceId: 'trace-1' }).values.clusters?.[0].label).toBe('Billing questions')
    })

    it('shows no clusters chip and no toast when the clusters read fails', async () => {
        const toast = jest.spyOn(lemonToast, 'error')
        clustersStatus = 500
        mountAt()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready' })
        expect(traceClustersLogic({ traceId: 'trace-1' }).values.clusters).toBeNull()
        expect(clusterRequests).toEqual([CREATED_AT])
        expect(toast).not.toHaveBeenCalled()
    })

    it.each([
        ['a root without state', 'gen-1'],
        ['a root with state', 'trace-1'],
    ])('reads only the default step and the thread when the trace opens on %s', async (_name, defaultNodeId) => {
        traceResource = makeTraceResource({ defaultNodeId })
        mountAt()
        await expectLogic(logic).toFinishAllListeners()

        expect([...nodeRequests].sort()).toEqual([defaultNodeId, 'gen-2'].sort())
    })

    it('reports the reads that open the view as navigation and a click on an unread step as a selection', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        traceResource = makeTraceResource({ defaultNodeId: 'gen-1' })
        mountAt()
        await expectLogic(logic).toFinishAllListeners()

        expect(nodeRequests).toContain('gen-1')
        expect(capture).toHaveBeenCalledWith('llma trace node loaded', {
            load_ms: expect.any(Number),
            trigger: 'navigation',
            waited_ms: null,
        })
        expect(capture).not.toHaveBeenCalledWith(
            'llma trace node loaded',
            expect.objectContaining({ trigger: 'selection' })
        )
        capture.mockClear()

        logic.actions.selectNode('span-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(capture).toHaveBeenCalledWith('llma trace node loaded', {
            load_ms: expect.any(Number),
            trigger: 'selection',
            waited_ms: expect.any(Number),
        })
    })

    it('prefetches only the row the pointer rests on, without rebuilding the shown step or the thread', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        nodeRequests = []
        const { selectedNodeLoad, thread } = logic.values

        logic.actions.prefetchNode('span-1')
        logic.actions.prefetchNode('gen-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(nodeRequests).toEqual(['gen-1'])
        expect(logic.values.selectedNodeLoad).toBe(selectedNodeLoad)
        expect(logic.values.thread).toBe(thread)
    })

    it('builds the thread from the thread node', async () => {
        mountAt()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                thread: expect.objectContaining({
                    status: 'ready',
                    turns: [
                        expect.objectContaining({
                            input: { kind: 'messages', messages: [expect.objectContaining({ role: 'user' })] },
                            output: { kind: 'messages', messages: [expect.objectContaining({ role: 'assistant' })] },
                        }),
                    ],
                }),
            })
    })

    it.each(['selectNode', 'selectAndShowSpans'] as const)(
        'reads a failed node again when %s picks it again',
        async (select) => {
            failingNodeId = 'span-1'
            mountAt({ requestedStepId: 'span-1' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.selectedNodeLoad.status).toBe('error')

            logic.actions[select]('span-1')
            await expectLogic(logic).toFinishAllListeners()

            expect(nodeRequests.filter((nodeId) => nodeId === 'span-1')).toHaveLength(2)
            expect(logic.values.selectedNodeLoad.status).toBe('ready')
        }
    )

    it('selecting from the thread or timeline switches to spans', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setMode('timeline')

        await expectLogic(logic, () => logic.actions.selectAndShowSpans('gen-1')).toMatchValues({
            mode: 'spans',
            selectedNodeId: 'gen-1',
        })
    })

    it.each([
        ['the first failing step in the tree', [{ nodeId: 'gen-1', outcome: 'fail' }], 'gen-1'],
        [
            'the root when no step in the tree fails',
            [
                { nodeId: 'gen-1', outcome: 'pass' },
                { nodeId: 'ghost', outcome: 'fail' },
            ],
            'trace-1',
        ],
    ] as const)('showFailingEvals opens the Evals tab of %s, in spans', async (_name, nodes, expected) => {
        evaluations = makeEvaluationResults({ summary: { passed: 1, failed: 1, unrated: 0, nodes: [...nodes] } })
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setMode('thread')

        await expectLogic(logic, () => logic.actions.showFailingEvals()).toMatchValues({
            selectedNodeId: expected,
            mode: 'spans',
            detailTab: 'evals',
        })
    })

    it.each([
        ['gen-2', 'the thread node', true],
        ['trace-1', 'the root', true],
        ['span-1', 'a span outside the thread', false],
    ])('canViewInThread for %s (%s) is %s', async (nodeId, _description, expected) => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.selectNode(nodeId)).toMatchValues({ canViewInThread: expected })
    })

    it('showFeedback opens the Feedback mode focused on the step, reports where it came from and keeps both on a click of its tab', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setMode('thread')

        await expectLogic(logic, () => logic.actions.showFeedback('gen-1', 'step')).toMatchValues({
            mode: 'feedback',
            feedbackFocusNodeId: 'gen-1',
        })
        expect(logic.values.selectedStepFeedback).toMatchObject({ nodeId: 'trace-1', total: 1 })
        expect(capture).toHaveBeenCalledWith('llma trace view feedback viewed', {
            entry: 'step',
            scores: 1,
            responses: 1,
            unanswered: 0,
        })

        await expectLogic(logic, () => logic.actions.setMode('feedback')).toMatchValues({
            mode: 'feedback',
            feedbackFocusNodeId: 'gen-1',
        })
        expect(capture.mock.calls.filter(([event]) => event === 'llma trace view feedback viewed')).toHaveLength(1)
    })

    it('takes the search from the host, then follows its changes', async () => {
        mountAt({ seedQuery: 'invoice' })

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ searchBox: expect.objectContaining({ query: 'invoice', status: 'ready', total: 3 }) })

        host.actions.setSeedQuery('refund')

        expect(logic.values.query).toBe('refund')
    })

    it('publishes only the settled search to the host', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setQuery('two')
            logic.actions.setQuery('two words + 50%')
        })
            .toDispatchActions(['setQuery'])
            .toFinishAllListeners()
            .toNotHaveDispatchedActions([host.actionCreators.publishQuery('two')])
            .toDispatchActions([host.actionCreators.publishQuery('two words + 50%')])
    })

    it('steps to the next match from another mode and shows it in spans', async () => {
        mountAt({ seedQuery: 'invoice' })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setMode('thread')

        await expectLogic(logic, () => logic.actions.stepMatch('next')).toMatchValues({
            mode: 'spans',
            selectedNodeId: 'gen-1',
            searchBox: expect.objectContaining({ position: 1 }),
        })
    })

    it('steps to the first match from a mode that does not show the selected step', async () => {
        mountAt({ seedQuery: 'invoice' })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.selectNode('gen-1')
        logic.actions.setMode('thread')

        expect(logic.values.searchBox.position).toBeNull()

        logic.actions.stepMatch('next')
        expect(logic.values).toMatchObject({ mode: 'spans', selectedNodeId: 'gen-1' })
    })

    it('drops the previous matches when a newer search fails', async () => {
        silenceKeaLoadersErrors()
        mountAt({ seedQuery: 'invoice' })
        await expectLogic(logic).toFinishAllListeners()
        searchStatus = 504

        logic.actions.setQuery('refund')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.stepMatch('next')

        expect(logic.values).toMatchObject({
            selectedNodeId: 'trace-1',
            searchBox: expect.objectContaining({ status: 'error', failure: 'too_slow', matchingSteps: 0 }),
        })
    })

    it('the Summary mode reads the summary on open, and a step link leaves it for that step in spans', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        const summary = traceSummaryLogic({ traceId: 'trace-1' })

        logic.actions.setMode('summary')
        await expectLogic(summary).toDispatchActions([summary.actionCreators.openSummary('tab'), 'loadSummarySuccess'])
        await expectLogic(logic, () => logic.actions.summaryStepClicked('gen-1', 'bullet')).toMatchValues({
            mode: 'spans',
            selectedNodeId: 'gen-1',
        })

        await expectLogic(summary).toDispatchActions(['closeSummary']).toMatchValues({ isOpen: false })
        expect(capture).toHaveBeenCalledWith('llma trace view summary step clicked', { kind: 'bullet' })
    })

    it('leaving the Summary mode for the Feedback mode closes the summary', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        const summary = traceSummaryLogic({ traceId: 'trace-1' })

        logic.actions.setMode('summary')
        await expectLogic(summary).toDispatchActions([summary.actionCreators.openSummary('tab'), 'loadSummarySuccess'])
        logic.actions.showFeedback(null, 'chip')

        expect(logic.values.mode).toBe('feedback')
        await expectLogic(summary).toDispatchActions(['closeSummary']).toMatchValues({ isOpen: false })
    })

    it('a trace-level summary link opens the Summary mode without requesting a summary', async () => {
        mountAt({ openingMode: 'summary' })
        const summary = traceSummaryLogic({ traceId: 'trace-1' })

        await expectLogic(summary)
            .toDispatchActions([summary.actionCreators.openSummary('link')])
            .toNotHaveDispatchedActions([summary.actionCreators.openSummary('tab')])
            .toDispatchActions(['loadSummarySuccess'])

        expect(logic.values.mode).toBe('summary')
        expect(traceSummaryLogic({ traceId: 'trace-1' }).values.state).toEqual({ status: 'none' })
        expect(summaryRequests).toBe(0)
    })

    it('a summary link that names a step opens that step instead of the Summary mode', async () => {
        mountAt({ openingMode: 'summary', requestedStepId: 'gen-1' })

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ mode: 'spans', selectedNodeId: 'gen-1' })
        expect(traceSummaryLogic({ traceId: 'trace-1' }).values.isOpen).toBe(false)
    })

    it('opens the summary of a new trace when the mode carries over', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setMode('summary')

        stepTo('trace-2')

        const summary = traceSummaryLogic({ traceId: 'trace-2' })
        await expectLogic(summary).toDispatchActions([summary.actionCreators.openSummary('tab'), 'loadSummarySuccess'])
        expect(summary.values.isOpen).toBe(true)
        expect(summaryRequests).toBe(0)
    })

    it('reads the raw event of the selected step when the Raw tab opens and again when the step changes', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        expect(rawRequests).toEqual([])

        logic.actions.setDetailTab('raw')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.selectNode('span-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(rawRequests).toEqual(['trace-1', 'span-1'])
        expect(logic.values.selectedRaw).toMatchObject({ status: 'ready' })
    })

    it('keeps the step detail when only its raw read changes', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        const { selectedNodeLoad } = logic.values

        logic.actions.setDetailTab('raw')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedRaw).toMatchObject({ status: 'ready' })
        expect(logic.values.selectedNodeLoad).toBe(selectedNodeLoad)
    })

    it('reads a failed raw event again when the same step is selected again', async () => {
        silenceKeaLoadersErrors()
        failingRawNodeId = 'span-1'
        mountAt({ requestedStepId: 'span-1' })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadRawNode('span-1')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.rawNodes.get('span-1')).toMatchObject({ status: 'error' })

        logic.actions.selectNode('span-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(rawRequests).toEqual(['span-1', 'span-1'])
        expect(logic.values.rawNodes.get('span-1')).toMatchObject({ status: 'ready' })
    })

    it('keeps mode and step tab when the trace changes', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setMode('timeline')
        logic.actions.setDetailTab('evals')

        stepTo('trace-2')

        expect(logic.values).toMatchObject({ mode: 'timeline', detailTab: 'evals' })
    })

    it('starts the next trace without the search query', async () => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setQuery('invoice')
        await expectLogic(logic).toFinishAllListeners()

        stepTo('trace-2')

        expect(logic.values.query).toBe('')
    })
})
