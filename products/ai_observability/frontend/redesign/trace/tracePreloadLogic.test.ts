import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    decodeIdSegment,
    makeEvaluationResults,
    makeNodeDetail,
    makeSeededRow,
    makeTraceResource,
} from './testFixtures'
import type { TraceListRow } from './traceListRows'
import { ROW_PREFETCH_DWELL_MS, tracePreloadLogic } from './tracePreloadLogic'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const CREATED_AT_A = '2026-09-01T10:15:00Z'
const CREATED_AT_B = '2026-09-01T10:20:00Z'

describe('tracePreloadLogic', () => {
    let requests: string[]
    let answerGate: Promise<void>
    let answerStatus: number
    let threadNodeIds: string[] | undefined

    beforeEach(() => {
        requests = []
        answerGate = Promise.resolve()
        answerStatus = 200
        threadNodeIds = undefined
        useMocks({
            get: {
                [TRACE_URL]: async ({ request, params }) => {
                    const traceId = decodeIdSegment(String(params.id))
                    requests.push(`trace ${traceId} ${new URL(request.url).searchParams.get('timestamp_hint')}`)
                    await answerGate
                    return answerStatus === 200
                        ? [200, makeTraceResource({ id: traceId, ...(threadNodeIds && { threadNodeIds }) })]
                        : [answerStatus, {}]
                },
                [NODE_URL]: async ({ request, params }) => {
                    const traceId = decodeIdSegment(String(params.id))
                    const nodeId = decodeIdSegment(String(params.node_id))
                    requests.push(
                        `node ${traceId} ${nodeId} ${new URL(request.url).searchParams.get('timestamp_hint')}`
                    )
                    await answerGate
                    return answerStatus === 200 ? [200, makeNodeDetail({ id: nodeId })] : [answerStatus, {}]
                },
                [EVALUATIONS_URL]: () => [200, makeEvaluationResults()],
            },
        })
        initKeaTests()
        tracePreloadLogic.mount()
        tracePreloadLogic.actions.seedRows([
            makeSeededRow({ id: 'a', createdAt: CREATED_AT_A }, 'gen-1'),
            makeSeededRow({ id: 'b', createdAt: CREATED_AT_B }, 'span-1'),
            makeSeededRow({ id: 'no-step' }),
        ])
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    function holdAnswers(): () => void {
        let release = (): void => {}
        answerGate = new Promise<void>((resolve) => {
            release = resolve
        })
        return release
    }

    function rest(traceId: string, restMs: number = ROW_PREFETCH_DWELL_MS): void {
        tracePreloadLogic.actions.rowEntered(traceId)
        jest.advanceTimersByTime(restMs)
    }

    async function settled(): Promise<void> {
        await waitFor(() => expect(tracePreloadLogic.values.prefetchInFlight).toBe(false))
    }

    function count(request: string): number {
        return requests.filter((made) => made.startsWith(request)).length
    }

    function readTraces(): string[] {
        return requests.filter((request) => request.startsWith('trace ')).map((request) => request.split(' ')[1])
    }

    it('keeps the rows that carry an overview, keyed by trace id', () => {
        tracePreloadLogic.actions.seedRows([
            makeSeededRow({ id: 'a', name: 'first' }, 'gen-1'),
            { traceId: 'plain', timestamp: null, stepId: null },
            makeSeededRow({ id: 'a', name: 'second' }),
        ])

        expect([...tracePreloadLogic.values.seeds]).toEqual([
            ['a', { overview: expect.objectContaining({ name: 'first' }), defaultStepId: 'gen-1' }],
        ])
    })

    it('prefetches the trace and its default step once the pointer has rested on a row', async () => {
        jest.useFakeTimers()
        rest('a', ROW_PREFETCH_DWELL_MS - 1)
        expect(tracePreloadLogic.values.prefetchInFlight).toBe(false)
        jest.advanceTimersByTime(1)
        jest.useRealTimers()
        await settled()

        expect(requests.sort()).toEqual([`node a gen-1 ${CREATED_AT_A}`, `trace a ${CREATED_AT_A}`])
    })

    it.each<[string, () => Promise<void>, string[]]>([
        [
            'the pointer leaves first',
            async () => {
                rest('a', ROW_PREFETCH_DWELL_MS - 1)
                tracePreloadLogic.actions.rowLeft()
                jest.advanceTimersByTime(ROW_PREFETCH_DWELL_MS)
            },
            [],
        ],
        [
            'it moves to another row first',
            async () => {
                rest('a', ROW_PREFETCH_DWELL_MS - 1)
                rest('b')
            },
            ['b'],
        ],
        ['the row has no default step', async () => rest('no-step'), []],
        [
            'another prefetch is in flight',
            async () => {
                const release = holdAnswers()
                rest('a')
                rest('b')
                release()
            },
            ['a'],
        ],
        [
            'the trace is already prefetched',
            async () => {
                rest('a')
                jest.useRealTimers()
                await settled()
                jest.useFakeTimers()
                rest('a')
            },
            ['a'],
        ],
    ])('starts no prefetch when %s', async (_name, act, expectedTraces) => {
        jest.useFakeTimers()
        await act()
        jest.useRealTimers()
        await settled()

        expect(readTraces()).toEqual(expectedTraces)
        expect(requests).toHaveLength(expectedTraces.length * 2)
    })

    it.each<[string, TraceListRow[], number]>([
        [
            'keeps a prefetch when new rows still list its trace under the same default step',
            [
                {
                    ...makeSeededRow({ id: 'a', createdAt: CREATED_AT_A }, 'gen-1'),
                    person: { distinctId: 'person-a', label: 'person-a@example.com' },
                },
            ],
            1,
        ],
        [
            'drops a prefetch when new rows no longer list its trace',
            [makeSeededRow({ id: 'b', createdAt: CREATED_AT_B }, 'span-1')],
            2,
        ],
        [
            'drops a prefetch when new rows list its trace under another default step',
            [makeSeededRow({ id: 'a', createdAt: CREATED_AT_A }, 'gen-2')],
            2,
        ],
        [
            'drops a prefetch when new rows list its trace with no default step',
            [makeSeededRow({ id: 'a', createdAt: CREATED_AT_A })],
            2,
        ],
        [
            'drops a prefetch when new rows list its trace with other totals',
            [
                makeSeededRow(
                    { id: 'a', createdAt: CREATED_AT_A, totals: { ...makeTraceResource().totals, inputTokens: 5120 } },
                    'gen-1'
                ),
            ],
            2,
        ],
    ])('%s', async (_name, rows, reads) => {
        jest.useFakeTimers()
        rest('a')
        jest.useRealTimers()
        await settled()

        tracePreloadLogic.actions.seedRows(rows)
        const view = traceViewLogic({ traceId: 'a', timestampHint: CREATED_AT_A })
        view.mount()
        view.actions.loadNode('gen-1', 'navigation')
        await expectLogic(view).toFinishAllListeners()
        await waitFor(() => expect(view.values.status).toBe('ready'))

        expect(count('trace a ')).toBe(reads)
        expect(count('node a gen-1 ')).toBe(reads)
    })

    it('reads the prefetched default step once when the trace opens at another step and threads the default one', async () => {
        threadNodeIds = ['gen-1']
        jest.useFakeTimers()
        rest('a')
        jest.useRealTimers()
        await settled()

        const view = traceViewLogic({ traceId: 'a', timestampHint: CREATED_AT_A })
        view.mount()
        view.actions.loadNode('gen-2', 'navigation')
        await waitFor(() => expect(view.values.nodes.get('gen-1')?.status).toBe('ready'))
        await expectLogic(view).toFinishAllListeners()

        expect(count('trace a ')).toBe(1)
        expect(count('node a gen-1 ')).toBe(1)
    })

    it.each([200, 500])(
        'prefetches again once the one in flight has answered with %s, and never surfaces a failure',
        async (status) => {
            const toast = jest.spyOn(lemonToast, 'error')
            const report = jest.spyOn(posthog, 'captureException')
            answerStatus = status
            const release = holdAnswers()
            jest.useFakeTimers()
            rest('a')
            jest.useRealTimers()
            release()
            await settled()

            jest.useFakeTimers()
            rest('b')
            jest.useRealTimers()
            await settled()

            expect(readTraces()).toEqual(['a', 'b'])
            expect(toast).not.toHaveBeenCalled()
            expect(report).not.toHaveBeenCalled()
        }
    )
})
