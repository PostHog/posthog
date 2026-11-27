import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceTimelineRowApi } from '../../generated/api.schemas'
import {
    decodeIdSegment,
    makeEvaluationResult,
    makeEvaluationResults,
    makeFeedback,
    makeNodeDetail,
    makeRawNode,
    makeSeededRow,
    makeTraceResource,
} from './testFixtures'
import { traceFeedbackLogic } from './traceFeedbackLogic'
import { tracePreloadLogic } from './tracePreloadLogic'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/'
const RAW_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/raw/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const FEEDBACK_URL = '/api/projects/:team_id/ai_observability/traces/:id/feedback/'
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
    let rawRequests: string[] = []
    let rawStatus = 200
    let nodeHints: (string | null)[] = []
    let nodeStatus = 200
    let nodeGate: Promise<void> = Promise.resolve()
    let firstNodeAnswer = deferred()

    beforeEach(() => {
        requestedHint = null
        requestedPath = null
        nodeRequests = []
        rawRequests = []
        rawStatus = 200
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
                [RAW_URL]: ({ params }) => {
                    const nodeId = decodeIdSegment(String(params.node_id))
                    rawRequests.push(nodeId)
                    return rawStatus === 200
                        ? [200, makeRawNode({ id: nodeId, properties: { $ai_model: 'gpt-4o' } })]
                        : [rawStatus, { detail: 'nope' }]
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

    it('loads the trace by its encoded id with the link timestamp as the hint', async () => {
        const logic = traceViewLogic({ traceId: 'a/b', timestampHint: '2026-09-01T10:15:00Z' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready' })
        expect(requestedPath).toMatch(/\/traces\/YS9i\/$/)
        expect(requestedHint).toEqual('2026-09-01T10:15:00Z')
        expect(logic.values.trace?.tree[0].children.map((child) => child.id)).toEqual(['span-1', 'gen-1', 'gen-2'])
    })

    describe('seeded from a list row', () => {
        const ROW_CREATED_AT = '2026-08-30T08:00:00Z'
        let heldTrace = deferred()

        beforeEach(() => {
            heldTrace = deferred()
            useMocks({
                get: {
                    [TRACE_URL]: async () => {
                        await heldTrace.promise
                        return [200, makeTraceResource()]
                    },
                },
            })
            tracePreloadLogic.mount()
            tracePreloadLogic.actions.seedRows([makeSeededRow({ name: 'row-name', createdAt: ROW_CREATED_AT })])
        })

        function mountSeeded(): ReturnType<typeof traceViewLogic.build> {
            const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
            logic.mount()
            return logic
        }

        it('shows the row overview while the trace loads, then the trace', async () => {
            const logic = mountSeeded()

            expect(logic.values).toMatchObject({ status: 'loading', overview: { name: 'row-name' } })
            heldTrace.resolve()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values).toMatchObject({ status: 'ready', overview: { name: 'answer-billing-question' } })
        })

        it('keeps the seeded overview when the list drops the row mid-load', async () => {
            const logic = mountSeeded()

            tracePreloadLogic.actions.seedRows([])

            expect(logic.values.overview?.name).toBe('row-name')
            heldTrace.resolve()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('sends the row time as the hint of a step read before the trace arrives', async () => {
            const logic = mountSeeded()

            logic.actions.loadNode('span-1', 'selection')
            await waitFor(() => expect(nodeRequests).toContain('span-1'))

            expect(nodeHints[nodeRequests.indexOf('span-1')]).toBe(ROW_CREATED_AT)
            heldTrace.resolve()
            await expectLogic(logic).toFinishAllListeners()
        })
    })

    describe('prefetched from a list row', () => {
        let traceRequests = 0
        let feedbackRequests = 0
        let traceStatus = 200
        let traceGate: Promise<void> = Promise.resolve()
        let now = Date.parse('2026-09-01T11:00:00Z')

        beforeEach(() => {
            traceRequests = 0
            feedbackRequests = 0
            traceStatus = 200
            traceGate = Promise.resolve()
            jest.spyOn(Date, 'now').mockImplementation(() => now)
            useMocks({
                get: {
                    [TRACE_URL]: async () => {
                        traceRequests += 1
                        await traceGate
                        return traceStatus === 200 ? [200, makeTraceResource()] : [traceStatus, { detail: 'nope' }]
                    },
                    [FEEDBACK_URL]: () => {
                        feedbackRequests += 1
                        return [200, makeFeedback()]
                    },
                },
            })
            tracePreloadLogic.mount()
            tracePreloadLogic.actions.seedRows([makeSeededRow({}, 'gen-1')])
        })

        function prefetch(): void {
            tracePreloadLogic.actions.prefetchTrace('trace-1')
        }

        async function settled(): Promise<void> {
            await waitFor(() => expect(tracePreloadLogic.values.prefetchInFlight).toBe(false))
        }

        async function open(): Promise<{ unmount: () => void }> {
            const feedback = traceFeedbackLogic({ traceId: 'trace-1', timestampHint: null })
            const unmount = feedback.mount()
            const view = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
            view.actions.loadNode('gen-1', 'navigation')
            await expectLogic(view).toFinishAllListeners()
            await waitFor(() => expect(view.values.status).toBe('ready'))
            return { unmount }
        }

        it.each(['in flight', 'answered'])(
            'opens a prefetched trace without a second read when it is %s',
            async (state) => {
                let releaseTrace = (): void => {}
                traceGate = new Promise<void>((resolve) => {
                    releaseTrace = resolve
                })
                prefetch()
                if (state === 'answered') {
                    releaseTrace()
                    await settled()
                }

                const opening = open()
                releaseTrace()
                await opening

                expect(traceRequests).toBe(1)
                expect(nodeRequests.filter((id) => id === 'gen-1')).toHaveLength(1)
                await waitFor(() => expect(feedbackRequests).toBe(1))
            }
        )

        it.each<[string, () => Promise<void>]>([
            [
                'the prefetch failed',
                async () => {
                    traceStatus = 500
                    nodeStatus = 500
                    prefetch()
                    await settled()
                    traceStatus = 200
                    nodeStatus = 200
                    await open()
                },
            ],
            [
                'the trace is opened a second time',
                async () => {
                    prefetch()
                    await settled()
                    const { unmount } = await open()
                    unmount()
                    await open()
                },
            ],
            [
                'the prefetch is older than 30 s',
                async () => {
                    prefetch()
                    await settled()
                    now += 30_001
                    await open()
                },
            ],
        ])('reads again when %s', async (_name, steps) => {
            const toast = jest.spyOn(lemonToast, 'error')

            await steps()

            expect(traceRequests).toBe(2)
            expect(nodeRequests.filter((id) => id === 'gen-1')).toHaveLength(2)
            expect(toast).not.toHaveBeenCalled()
        })
    })

    it.each([
        ['the trace is not found', 404, 'not_found'],
        ['the request fails', 500, 'failed'],
    ])('status is error when %s', async (_description, statusCode, expectedFailure) => {
        silenceKeaLoadersErrors()
        useMocks({ get: { [TRACE_URL]: () => [statusCode, { detail: 'nope' }] } })
        const logic = traceViewLogic({ traceId: 'trace-1', timestampHint: null })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'error', loadFailure: expectedFailure })
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
        expect(logic.values.nodes.get('gen-2')).toMatchObject({ status: 'ready' })
    })

    it.each(['span-1', 'constructor'])('reads node %s once, however many times it is asked for', async (nodeId) => {
        const logic = await mountedLogic()

        logic.actions.loadNode(nodeId, 'prefetch')
        logic.actions.loadNode(nodeId, 'selection')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadNode(nodeId, 'selection')
        await expectLogic(logic).toFinishAllListeners()

        expect(nodeRequests.filter((id) => id === nodeId)).toHaveLength(1)
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
            expect(logic.values.nodes.get('gen-1')).toBeUndefined()

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
        [404, 'not_found', false],
        [500, 'failed', true],
        [503, 'failed', false],
    ])(
        'a node read answered with %s fails as %s, reported to error tracking: %s',
        async (status, failure, reported) => {
            const report = jest.spyOn(posthog, 'captureException')
            const logic = await mountedLogic()
            nodeStatus = status

            logic.actions.loadNode('span-1', 'selection')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.nodes.get('span-1')).toEqual({ status: 'error', failure })
            expect(report).toHaveBeenCalledTimes(reported ? 1 : 0)
        }
    )

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
            expect(logic.values.nodes.get('span-1')).toMatchObject({ status: 'error' })

            logic.actions.loadNode('span-1', trigger)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.nodes.get('span-1')).toMatchObject({ status: 'ready' })
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

    it.each([
        ['2026-09-01T10:15:00Z', 2.5],
        ['2026-09-01T12:15:00+02:00', 2.5],
        ['invalid', null],
    ])('reports trace age and read timing for timestamp %s', async (createdAt, traceAgeMinutes) => {
        jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-09-01T10:17:30Z'))
        useMocks({ get: { [TRACE_URL]: () => [200, makeTraceResource({ createdAt })] } })
        const capture = jest.spyOn(posthog, 'capture')
        const logic = await mountedLogic()

        logic.actions.loadNode('span-1', 'prefetch')
        logic.actions.loadNode('span-1', 'selection')
        logic.actions.loadNode('gen-1', 'navigation')
        await expectLogic(logic).toFinishAllListeners()

        expect(capture).toHaveBeenCalledWith('llma trace view loaded', {
            trace_load_ms: expect.any(Number),
            node_count: 4,
            trace_age_minutes: traceAgeMinutes,
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
        expect(reopened.values.nodes.get(nodeId)).toBeUndefined()
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

                expect(logic.values.nodes.get(nodeId)).toMatchObject({ status: expectedStatus })
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

    describe('raw reads', () => {
        it('reads a step raw event once, however many times it is asked for', async () => {
            const logic = await mountedLogic()

            logic.actions.loadRawNode('span-1')
            logic.actions.loadRawNode('span-1')
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadRawNode('span-1')
            await expectLogic(logic).toFinishAllListeners()

            expect(rawRequests).toEqual(['span-1'])
        })

        it('stores the raw event once it arrives', async () => {
            const logic = await mountedLogic()

            logic.actions.loadRawNode('span-1')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.rawNodes.get('span-1')).toMatchObject({
                status: 'ready',
                raw: { id: 'span-1', event: { properties: { $ai_model: 'gpt-4o' } } },
            })
        })

        it('stores not_found for a missing step and reads it again on the next request', async () => {
            silenceKeaLoadersErrors()
            const logic = await mountedLogic()
            rawStatus = 404

            logic.actions.loadRawNode('span-1')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.rawNodes.get('span-1')).toEqual({ status: 'error', failure: 'not_found' })

            rawStatus = 200
            logic.actions.loadRawNode('span-1')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.rawNodes.get('span-1')).toMatchObject({ status: 'ready' })
        })
    })

    it('has no evaluation outcomes when the evaluations read fails', async () => {
        silenceKeaLoadersErrors()
        useMocks({ get: { [EVALUATIONS_URL]: () => [500, { detail: 'Server error.' }] } })

        const logic = await mountedLogic()

        expect(logic.values).toMatchObject({ evaluationResults: null, evalOutcomes: new Map() })
    })

    it('indexes the evaluation outcomes by node id', async () => {
        const nodes = [
            { nodeId: 'gen-1', outcome: 'fail' as const },
            { nodeId: 'constructor', outcome: 'pass' as const },
        ]
        useMocks({
            get: {
                [EVALUATIONS_URL]: () => [
                    200,
                    makeEvaluationResults({ summary: { passed: 1, failed: 1, unrated: 0, nodes } }),
                ],
            },
        })

        const logic = await mountedLogic()

        expect([...logic.values.evalOutcomes]).toEqual([
            ['gen-1', 'fail'],
            ['constructor', 'pass'],
        ])
    })

    it('indexes the step labels the trace sends by node id', async () => {
        const trace = makeTraceResource()
        trace.tree[0].children[1].label = 'openai.chat #2'
        useMocks({ get: { [TRACE_URL]: () => [200, trace] } })

        const logic = await mountedLogic()

        expect(logic.values.stepLabels.get('gen-1')).toBe('openai.chat #2')
        expect(logic.values.stepLabels.get('trace-1')).toBe('answer-billing-question')
    })
})
