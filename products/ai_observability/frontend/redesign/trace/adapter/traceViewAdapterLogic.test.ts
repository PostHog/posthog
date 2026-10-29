import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { aiObservabilityTraceLogic } from '../../../aiObservabilityTraceLogic'
import type { TraceApi, TraceEvaluationResultsApi } from '../../../generated/api.schemas'
import { traceSummaryLogic } from '../traceSummaryLogic'
import {
    decodeIdSegment,
    makeEvaluationResults,
    makeFeedback,
    makeNodeDetail,
    makeTraceCluster,
    makeTraceResource,
} from './testFixtures'
import { traceViewAdapterLogic } from './traceViewAdapterLogic'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const CLUSTERS_URL = '/api/projects/:team_id/ai_observability/traces/:id/clusters/'
const CREATED_AT = '2026-09-01T10:15:00Z'
const FEEDBACK_URL = '/api/projects/:team_id/ai_observability/traces/:id/feedback/'
const SUMMARY_URL = '/api/projects/:team_id/ai_observability/traces/:id/summary/'

const answeredGeneration = makeNodeDetail({
    id: 'gen-2',
    properties: {
        $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
        $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
    },
    ioKeys: { input: '$ai_input', output: '$ai_output_choices' },
})

describe('traceViewAdapterLogic', () => {
    let logic: ReturnType<typeof traceViewAdapterLogic.build>
    let traceResource: TraceApi
    let traceGate: Promise<void>
    let nodeRequests: string[]
    let failingNodeId: string | null
    let clusterRequests: string[]
    let clustersStatus: number
    let feedbackStatus: number
    let summaryRequests: number
    let evaluations: TraceEvaluationResultsApi

    function mountAt(params: Record<string, string> = {}): void {
        router.actions.push(urls.aiObservabilityTrace('trace-1', params))
        logic = traceViewAdapterLogic({ traceId: 'trace-1', timestampHint: null })
        logic.mount()
    }

    beforeEach(() => {
        traceResource = makeTraceResource({ nodeIdsByAlias: { 'sdk-gen-1': 'gen-1' } })
        traceGate = Promise.resolve()
        nodeRequests = []
        failingNodeId = null
        clusterRequests = []
        clustersStatus = 200
        feedbackStatus = 200
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
                    feedbackStatus === 200 ? [200, makeFeedback()] : [feedbackStatus, { detail: 'Server error.' }],
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
                    const known = ['trace-1', 'span-1', 'gen-1'].includes(nodeId)
                    return known ? [200, makeNodeDetail({ id: nodeId })] : [404, { detail: 'Node not found.' }]
                },
            },
        })
        initKeaTests()
        jest.mocked(performQuery).mockReset()
        jest.mocked(performQuery).mockResolvedValue({ results: [] })
        aiObservabilityTraceLogic.mount()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('reads a deep-linked node alongside the trace, then the thread node, and never runs the legacy trace query', async () => {
        let releaseTrace = (): void => {}
        traceGate = new Promise<void>((resolve) => {
            releaseTrace = resolve
        })
        mountAt({ event: 'span-1' })

        await waitFor(() => expect(nodeRequests).toEqual(['span-1']))
        expect(logic.values.status).toBe('loading')

        releaseTrace()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready', selectedNodeId: 'span-1' })

        expect(nodeRequests).toEqual(['span-1', 'gen-2'])
        expect(jest.mocked(performQuery).mock.calls.some(([query]) => query.kind === 'TraceQuery')).toBe(false)
    })

    it.each([
        ['a node in the tree', { event: 'span-1' }, 'span-1'],
        ['an SDK id through its alias', { event: 'sdk-gen-1' }, 'gen-1'],
        ['a stale id as the root', { event: 'missing' }, 'trace-1'],
        ['no id as the default node', {}, 'gen-1'],
        ['a trace-level link as the root', { tab: 'summary' }, 'trace-1'],
    ])('selects %s', async (_name, params: Record<string, string>, expected) => {
        traceResource = makeTraceResource({ defaultNodeId: 'gen-1', nodeIdsByAlias: { 'sdk-gen-1': 'gen-1' } })
        mountAt(params)

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ selectedNodeId: expected })
        expect(logic.values.detailData?.content.kind).not.toBe('error')
    })

    it('asks for the neighbours once the trace arrives', async () => {
        mountAt()

        await expectLogic(logic).toDispatchActions([
            aiObservabilityTraceLogic.actionCreators.loadNeighbors('trace-1', '2026-09-01T10:15:00Z'),
        ])
    })

    it('asks for the clusters with the trace start once the trace arrives', async () => {
        let releaseTrace = (): void => {}
        traceGate = new Promise<void>((resolve) => {
            releaseTrace = resolve
        })
        mountAt()

        await waitFor(() => expect(nodeRequests).toEqual(['trace-1']))
        expect(clusterRequests).toEqual([])
        expect(logic.values.clustersChip).toBeNull()

        releaseTrace()
        await expectLogic(logic).toFinishAllListeners()

        expect(clusterRequests).toEqual([CREATED_AT])
        expect(logic.values.clustersChip?.first.label).toBe('Billing questions')
    })

    it('shows no clusters chip and no toast when the clusters read fails', async () => {
        const toast = jest.spyOn(lemonToast, 'error')
        clustersStatus = 500
        mountAt()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready', clustersChip: null })
        expect(clusterRequests).toEqual([CREATED_AT])
        expect(toast).not.toHaveBeenCalled()
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
        const { detailData, thread } = logic.values

        logic.actions.prefetchNode('span-1')
        logic.actions.prefetchNode('gen-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(nodeRequests).toEqual(['gen-1'])
        expect(logic.values.detailData).toBe(detailData)
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
                            messages: [
                                expect.objectContaining({ role: 'user' }),
                                expect.objectContaining({ role: 'assistant' }),
                            ],
                        }),
                    ],
                }),
            })
    })

    it.each(['selectNode', 'selectAndShowSpans'] as const)(
        'reads a failed node again when %s picks it again',
        async (select) => {
            failingNodeId = 'span-1'
            mountAt({ event: 'span-1' })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.detailData?.content.kind).toBe('error')

            logic.actions[select]('span-1')
            await expectLogic(logic).toFinishAllListeners()

            expect(nodeRequests.filter((nodeId) => nodeId === 'span-1')).toHaveLength(2)
            expect(logic.values.detailData?.content.kind).toBe('io')
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

    it('has no evals chip and no step markers when the evaluations read fails', async () => {
        useMocks({ get: { [EVALUATIONS_URL]: () => [500, { detail: 'Server error.' }] } })
        mountAt()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ evalsChip: null, evalOutcomesByNode: {} })
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
            feedbackChip: { total: 2 },
            feedbackCountByNodeId: { 'gen-1': 1, 'trace-1': 1 },
        })
        expect(capture).toHaveBeenCalledWith('llma trace view feedback viewed', {
            entry: 'step',
            scores: 1,
            responses: 1,
        })

        await expectLogic(logic, () => logic.actions.setMode('feedback')).toMatchValues({
            mode: 'feedback',
            feedbackFocusNodeId: 'gen-1',
        })
        expect(capture.mock.calls.filter(([event]) => event === 'llma trace view feedback viewed')).toHaveLength(1)
    })

    it('has no chip, no counts and an error mode after the feedback read fails', async () => {
        silenceKeaLoadersErrors()
        feedbackStatus = 500
        mountAt()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                status: 'ready',
                feedbackChip: null,
                feedbackCountByNodeId: {},
                feedbackMode: { status: 'error' },
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
        mountAt({ tab: 'summary' })
        const summary = traceSummaryLogic({ traceId: 'trace-1' })

        await expectLogic(summary).toDispatchActions([summary.actionCreators.openSummary('link'), 'loadSummarySuccess'])

        expect(logic.values).toMatchObject({ mode: 'summary', summaryState: { status: 'none' } })
        expect(summaryRequests).toBe(0)
    })

    it('a summary link that names a step opens that step instead of the Summary mode', async () => {
        mountAt({ tab: 'summary', event: 'gen-1' })

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ mode: 'spans', selectedNodeId: 'gen-1' })
        expect(traceSummaryLogic({ traceId: 'trace-1' }).values.isOpen).toBe(false)
    })
})
