import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceTimelineRowApi } from '../../generated/api.schemas'
import {
    decodeIdSegment,
    makeEvaluationResult,
    makeEvaluationResults,
    makeNodeDetail,
    makeTraceResource,
} from './adapter/testFixtures'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const answered = makeEvaluationResults({ results: [makeEvaluationResult()] })
const EXPIRED_ROW: TraceTimelineRowApi = {
    id: 'expired-1',
    kind: 'span',
    name: 'expired-1',
    depth: 0,
    startMs: 0,
    durationMs: null,
    hasError: false,
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

describe('traceViewLogic', () => {
    let requestedHint: string | null = null
    let requestedPath: string | null = null
    let nodeRequests: string[] = []
    let nodeHints: (string | null)[] = []
    let nodeStatus = 200
    let nodeGate: Promise<void> = Promise.resolve()
    let firstNodeAnswer = deferred()

    beforeEach(() => {
        requestedHint = null
        requestedPath = null
        nodeRequests = []
        nodeHints = []
        nodeStatus = 200
        nodeGate = Promise.resolve()
        firstNodeAnswer = deferred()
        useMocks({
            get: {
                // `expired-*` ids stand for nodes of a trace past the ai_events retention: the backend only finds
                // them when the read carries a timestamp hint.
                [NODE_URL]: async ({ request, params }) => {
                    const nodeId = decodeIdSegment(String(params.node_id))
                    const hint = new URL(request.url).searchParams.get('timestamp_hint')
                    nodeRequests.push(nodeId)
                    nodeHints.push(hint)
                    await nodeGate
                    firstNodeAnswer.resolve()
                    if (nodeId.startsWith('expired-') && !hint) {
                        return [404, { detail: 'Node not found.' }]
                    }
                    return nodeStatus === 200 ? [200, makeNodeDetail({ id: nodeId })] : [nodeStatus, { detail: 'nope' }]
                },
                [TRACE_URL]: ({ request }) => {
                    const url = new URL(request.url)
                    requestedHint = url.searchParams.get('timestamp_hint')
                    requestedPath = url.pathname
                    return [200, makeTraceResource({ name: null })]
                },
                [EVALUATIONS_URL]: () => [200, makeEvaluationResults()],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    async function mountedLogic(): Promise<ReturnType<typeof traceViewLogic.build>> {
        const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        return logic
    }

    // Regression: an override left behind on unmount keeps the nav collapsed on every other page.
    it.each([
        ['expanded', false],
        ['collapsed', true],
    ])('collapses the nav while open and restores it %s on close', async (_name, collapsedBefore) => {
        panelLayoutLogic.mount()
        panelLayoutLogic.actions.setLayoutNavCollapsedDesktop(collapsedBefore)
        const logic = await mountedLogic()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(true)
        logic.unmount()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(collapsedBefore)
    })

    it('loads the trace by its encoded id with the link timestamp as the hint and derives the summary', async () => {
        const logic = traceViewLogic({ traceId: 'a/b', timestampHint: '2026-09-01T10:15:00Z' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready', traceName: 'Untitled trace' })
        expect(requestedPath).toMatch(/\/traces\/YS9i\/$/)
        expect(requestedHint).toEqual('2026-09-01T10:15:00Z')
        expect(logic.values.personLabel).toBe('ada@example.com')
        expect(logic.values.summary?.person).toEqual({
            label: 'ada@example.com',
            href: expect.stringContaining('user-1'),
        })
        expect(logic.values.tree[0].children.map((child) => child.id)).toEqual(['span-1', 'gen-1', 'gen-2'])
    })

    it.each([
        ['the trace is not found', 404, 'It may have been deleted, or it is outside the retention period.'],
        ['the request fails', 500, 'Something went wrong while loading it. Try again in a moment.'],
    ])('status is error when %s', async (_description, statusCode, expectedMessage) => {
        silenceKeaLoadersErrors()
        useMocks({ get: { [TRACE_URL]: () => [statusCode, { detail: 'nope' }] } })
        const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ status: 'error', errorMessage: expectedMessage })
    })

    it.each([
        ['answers', 200, { evaluationResults: answered, evaluationResultsFailed: false }, false],
        ['fails', 500, { evaluationResults: null, evaluationResultsFailed: true }, true],
    ] as const)(
        'reads the evaluation results alongside the trace and keeps the trace ready, without a toast, when that read %s',
        async (_description, statusCode, expected, reported) => {
            const toast = jest.spyOn(lemonToast, 'error')
            const report = jest.spyOn(posthog, 'captureException')
            const traceAnswer = deferred()
            let traceAnswered = false
            let evaluationsReadBeforeTrace = false
            useMocks({
                get: {
                    [TRACE_URL]: async () => {
                        await traceAnswer.promise
                        traceAnswered = true
                        return [200, makeTraceResource()]
                    },
                    [EVALUATIONS_URL]: () => {
                        evaluationsReadBeforeTrace = !traceAnswered
                        return statusCode === 200 ? [200, answered] : [statusCode, { detail: 'nope' }]
                    },
                },
            })
            const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
            logic.mount()

            await waitFor(() => expect(logic.values.evaluationResultsLoading).toBe(false))
            expect(evaluationsReadBeforeTrace).toBe(true)
            traceAnswer.resolve()

            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({ ...expected, status: 'ready' })
            expect(toast).not.toHaveBeenCalled()
            expect(report).toHaveBeenCalledTimes(reported ? 1 : 0)
        }
    )

    it('loads the thread nodes once the trace arrives', async () => {
        const logic = await mountedLogic()

        expect(nodeRequests).toEqual(['gen-2'])
        expect(logic.values.nodes['gen-2']).toMatchObject({ status: 'ready' })
    })

    it('reads each node once, however many times it is asked for', async () => {
        const logic = await mountedLogic()

        logic.actions.loadNode('span-1', 'prefetch')
        logic.actions.loadNode('span-1', 'selection')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadNode('span-1', 'selection')
        await expectLogic(logic).toFinishAllListeners()

        expect(nodeRequests.filter((id) => id === 'span-1')).toHaveLength(1)
    })

    it.each([
        ['a later prefetch once the first one is answered', 'prefetch', 200],
        ['a later prefetch once the first one fails', 'prefetch', 500],
        ['a selection while the first one is in flight', 'selection', 200],
    ] as const)(
        'drops a prefetch while another is in flight, then reads the node for %s',
        async (_description, trigger, firstStatus) => {
            const logic = await mountedLogic()
            const firstPrefetch = deferred()
            nodeGate = firstPrefetch.promise
            nodeStatus = firstStatus
            nodeRequests = []

            logic.actions.loadNode('span-1', 'prefetch')
            logic.actions.loadNode('gen-1', 'prefetch')
            expect(logic.values.nodes['gen-1']).toBeUndefined()

            if (trigger === 'prefetch') {
                firstPrefetch.resolve()
                await expectLogic(logic).toFinishAllListeners()
            }
            logic.actions.loadNode('gen-1', trigger)
            firstPrefetch.resolve()
            await expectLogic(logic).toFinishAllListeners()

            expect([...nodeRequests].sort()).toEqual(['gen-1', 'span-1'])
        }
    )

    it.each([
        [404, 'not_found'],
        [500, 'failed'],
    ])('a node read answered with %s fails as %s', async (status, failure) => {
        const logic = await mountedLogic()
        nodeStatus = status

        logic.actions.loadNode('span-1', 'selection')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.nodes['span-1']).toEqual({ status: 'error', failure })
    })

    it.each(['selection', 'navigation'] as const)(
        'retries a failed node on a %s but not on a prefetch',
        async (trigger) => {
            const logic = await mountedLogic()
            nodeStatus = 500
            logic.actions.loadNode('span-1', trigger)
            await expectLogic(logic).toFinishAllListeners()
            nodeStatus = 200

            logic.actions.loadNode('span-1', 'prefetch')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.nodes['span-1']).toMatchObject({ status: 'error' })

            logic.actions.loadNode('span-1', trigger)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.nodes['span-1']).toMatchObject({ status: 'ready' })
        }
    )

    it('times a retried read from the click that retries it', async () => {
        const logic = await mountedLogic()
        const capture = jest.spyOn(posthog, 'capture')
        let now = 1000
        jest.spyOn(performance, 'now').mockImplementation(() => now)
        nodeStatus = 500
        logic.actions.loadNode('span-1', 'selection')
        await expectLogic(logic).toFinishAllListeners()

        now = 5000
        nodeStatus = 200
        logic.actions.loadNode('span-1', 'selection')
        await expectLogic(logic).toFinishAllListeners()

        expect(capture).toHaveBeenCalledWith('llma trace node loaded', {
            load_ms: 0,
            trigger: 'selection',
            waited_ms: 0,
        })
    })

    it('reports how long the reads took and how long a click waited', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const logic = await mountedLogic()

        logic.actions.loadNode('span-1', 'prefetch')
        logic.actions.loadNode('span-1', 'selection')
        logic.actions.loadNode('gen-1', 'navigation')
        await expectLogic(logic).toFinishAllListeners()

        expect(capture).toHaveBeenCalledWith('llma trace view loaded', {
            trace_load_ms: expect.any(Number),
            node_count: 0,
        })
        expect(capture).toHaveBeenCalledWith('llma trace node loaded', {
            load_ms: expect.any(Number),
            trigger: 'thread',
            waited_ms: null,
        })
        expect(capture).toHaveBeenCalledWith('llma trace node loaded', {
            load_ms: expect.any(Number),
            trigger: 'prefetch',
            waited_ms: expect.any(Number),
        })
        expect(capture).toHaveBeenCalledWith('llma trace node loaded', {
            load_ms: expect.any(Number),
            trigger: 'navigation',
            waited_ms: null,
        })
    })

    it.each([
        ['misses', 'expired-1'],
        ['succeeds', 'closed-1'],
    ])('drops a read that %s after the view is closed, even once the trace is open again', async (_, nodeId) => {
        useMocks({ get: { [TRACE_URL]: () => [200, makeTraceResource({ timeline: [EXPIRED_ROW] })] } })
        const heldNodeReads = deferred()
        nodeGate = heldNodeReads.promise
        const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
        logic.mount()
        logic.actions.loadNode(nodeId, 'selection')
        await expectLogic(logic).toDispatchActions(['loadTraceSuccess'])
        logic.unmount()
        const reopened = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
        reopened.mount()
        await expectLogic(reopened).toDispatchActions(['loadTraceSuccess'])
        heldNodeReads.resolve()

        await expectLogic(reopened).toFinishAllListeners()

        expect(nodeRequests.filter((id) => id === nodeId)).toHaveLength(1)
        expect(reopened.values.nodes[nodeId]).toBeUndefined()
    })

    describe('nodes of a trace past the ai_events retention', () => {
        it.each([
            ['trace', 'expired-1', [null, '2026-09-01T10:15:00Z'], 'ready'],
            ['node', 'expired-1', [null, '2026-09-01T10:15:00Z'], 'ready'],
            ['trace', 'expired-9', [null], 'error'],
            ['node', 'expired-9', [null], 'error'],
        ])(
            'when the %s response comes first, an early read of %s is sent with %j and ends as %s',
            async (firstResponse, nodeId, expectedHints, expectedStatus) => {
                const heldNodeReads = deferred()
                if (firstResponse === 'trace') {
                    nodeGate = heldNodeReads.promise
                }
                useMocks({
                    get: {
                        [TRACE_URL]: async () => {
                            if (firstResponse === 'node') {
                                await firstNodeAnswer.promise
                            }
                            return [200, makeTraceResource({ timeline: [EXPIRED_ROW] })]
                        },
                    },
                })
                const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: '2026-09-01T10:15:00Z' })
                logic.mount()
                logic.actions.loadNode(nodeId, 'selection')
                if (firstResponse === 'trace') {
                    await expectLogic(logic).toDispatchActions(['loadTraceSuccess'])
                    heldNodeReads.resolve()
                }

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.nodes[nodeId]).toMatchObject({ status: expectedStatus })
                expect(nodeHints.filter((_, index) => nodeRequests[index] === nodeId)).toEqual(expectedHints)
            }
        )

        it('times a reread from the first request to its answer', async () => {
            const capture = jest.spyOn(posthog, 'capture')
            let now = 1000
            jest.spyOn(performance, 'now').mockImplementation(() => now)
            const heldTrace = deferred()
            useMocks({
                get: {
                    [TRACE_URL]: async () => {
                        await heldTrace.promise
                        return [200, makeTraceResource({ timeline: [EXPIRED_ROW] })]
                    },
                },
            })
            const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
            logic.mount()
            logic.actions.loadNode('expired-1', 'selection')
            await expectLogic(logic).toDispatchActions(['nodeMissedWithoutHint'])

            const heldReread = deferred()
            nodeGate = heldReread.promise
            now = 3000
            heldTrace.resolve()
            await expectLogic(logic).toDispatchActions(['loadTraceSuccess'])
            now = 7000
            heldReread.resolve()
            await expectLogic(logic).toFinishAllListeners()

            expect(capture).toHaveBeenCalledWith('llma trace node loaded', {
                load_ms: 6000,
                trigger: 'selection',
                waited_ms: 6000,
            })
        })
    })
})
