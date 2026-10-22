import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { aiObservabilityTraceLogic } from '../../../aiObservabilityTraceLogic'
import type { TraceApi } from '../../../generated/api.schemas'
import { decodeIdSegment, makeNodeDetail, makeTraceResource } from './testFixtures'
import { traceViewAdapterLogic } from './traceViewAdapterLogic'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('../../../utils', () => ({
    ...jest.requireActual('../../../utils'),
    queryEvaluationRuns: jest.fn().mockResolvedValue([]),
}))

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/'

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
        useMocks({
            get: {
                [TRACE_URL]: async () => {
                    await traceGate
                    return [200, traceResource]
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

    it.each([
        ['gen-2', 'the thread node', true],
        ['trace-1', 'the root', true],
        ['span-1', 'a span outside the thread', false],
    ])('canViewInThread for %s (%s) is %s', async (nodeId, _description, expected) => {
        mountAt()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.selectNode(nodeId)).toMatchValues({ canViewInThread: expected })
    })
})
