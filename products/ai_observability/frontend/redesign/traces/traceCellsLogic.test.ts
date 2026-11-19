import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { TraceListApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import {
    TRACE_CELL_URLS,
    makeTraceCellsAnswer,
    makeTraceListItem,
    makeTraceListPage,
    makeTracePersonItem,
    makeTracePreview,
    makeTraceSentimentItem,
    ready,
} from './testFixtures'
import { type TraceCellRead, traceCellsLogic } from './traceCellsLogic'
import { TRACES_LIST_FILTERS, tracesListLogic } from './tracesListLogic'

const TRACES_URL = '/api/projects/:team_id/ai_observability/traces/'
const FIRST_PAGE_IDS = ['trace-a', 'trace-b', 'trace-c']
const FIRST_PAGE: TraceListApi = {
    items: [
        makeTraceListItem({ id: 'trace-a', createdAt: '2026-09-01T10:15:00Z' }),
        makeTraceListItem({ id: 'trace-b', createdAt: '2026-08-30T08:00:00Z' }),
        makeTraceListItem({ id: 'trace-c', createdAt: '2026-08-31T23:59:00Z' }),
    ],
    counts: null,
    nextCursor: 'cursor-2',
    previousCursor: null,
}
const SECOND_PAGE = makeTraceListPage(['trace-d'])
const MODEL_FILTER: AnyPropertyFilter = {
    key: '$ai_model',
    value: ['gpt-4'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}
const FAILED: [number, unknown] = [500, { detail: 'boom' }]

type CellBody = { trace_ids: string[]; earliest_created_at?: string; latest_created_at?: string }
type CellAnswer = [number, unknown]

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

function answerFor(read: TraceCellRead, traceIds: string[]): CellAnswer {
    return [200, makeTraceCellsAnswer(read, traceIds)]
}

describe('traceCellsLogic', () => {
    let bodies: Record<TraceCellRead, CellBody[]>
    let answer: (read: TraceCellRead, body: CellBody) => CellAnswer | Promise<CellAnswer>
    let firstPage: TraceListApi
    let logic: ReturnType<typeof traceCellsLogic.build>

    const requestedIds = (read: TraceCellRead): string[][] => bodies[read].map((body) => body.trace_ids)
    const statuses = (loads: ReadonlyMap<string, { status: string }>, ids: string[]): string[] =>
        ids.map((id) => loads.get(id)?.status ?? 'none')

    async function settle(): Promise<void> {
        await expectLogic(tracesListLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
    }

    function mount(): void {
        router.actions.push(urls.aiObservabilityTraces())
        logic = traceCellsLogic()
        logic.mount()
    }

    async function mountList(): Promise<void> {
        mount()
        await settle()
    }

    beforeEach(() => {
        localStorage.clear()
        bodies = { previews: [], people: [], sentiment: [] }
        answer = (read, body) => answerFor(read, body.trace_ids)
        firstPage = FIRST_PAGE
        const cellHandler =
            (read: TraceCellRead) =>
            async ({ request }: { request: Request }): Promise<CellAnswer> => {
                const body: CellBody = await request.json()
                bodies[read].push(body)
                return answer(read, body)
            }
        useMocks({
            get: {
                [TRACES_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    if (params.has('properties')) {
                        return [200, makeTraceListPage(['trace-c', 'trace-e'])]
                    }
                    return [200, params.get('cursor') === 'cursor-2' ? SECOND_PAGE : firstPage]
                },
            },
            post: {
                [TRACE_CELL_URLS.previews]: cellHandler('previews'),
                [TRACE_CELL_URLS.people]: cellHandler('people'),
                [TRACE_CELL_URLS.sentiment]: cellHandler('sentiment'),
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it("reads the three cells of a new page with its ids and its rows' time bounds", async () => {
        await mountList()

        const bounds = { earliest_created_at: '2026-08-30T08:00:00Z', latest_created_at: '2026-09-01T10:15:00Z' }
        expect(bodies).toEqual({
            previews: [{ trace_ids: FIRST_PAGE_IDS }],
            people: [{ trace_ids: FIRST_PAGE_IDS, ...bounds }],
            sentiment: [{ trace_ids: FIRST_PAGE_IDS, ...bounds }],
        })
        expect(logic.values.previews.get('trace-b')).toEqual(ready(makeTracePreview('trace-b')))
        expect(logic.values.people.get('trace-b')).toEqual(ready(makeTracePersonItem('trace-b').person))
        expect(logic.values.sentiments.get('trace-b')).toEqual(ready(makeTraceSentimentItem('trace-b').sentiment))
    })

    it('reads and fills a row whose id is an inherited object member', async () => {
        firstPage = makeTraceListPage(['constructor'])

        await mountList()

        expect(requestedIds('previews')).toEqual([['constructor']])
        expect(logic.values.previews.get('constructor')).toEqual(ready(makeTracePreview('constructor')))
    })

    it('reads nothing and tracks nothing when the person steps back to a page it read', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        await mountList()

        tracesListLogic.actions.showNextPage()
        await settle()
        tracesListLogic.actions.showPreviousPage()
        tracesListLogic.actions.showNextPage()
        await settle()

        expect(requestedIds('previews')).toEqual([FIRST_PAGE_IDS, ['trace-d']])
        expect(requestedIds('people')).toEqual([FIRST_PAGE_IDS, ['trace-d']])
        expect(requestedIds('sentiment')).toEqual([FIRST_PAGE_IDS, ['trace-d']])
        expect(capture.mock.calls.filter(([event]) => event === 'llma traces list cells loaded')).toEqual([
            ['llma traces list cells loaded', { previews_wait_ms: expect.any(Number), row_count: 3 }],
            ['llma traces list cells loaded', { previews_wait_ms: expect.any(Number), row_count: 1 }],
        ])
    })

    it('keeps what it read across a filter change and reads only the rows it does not know', async () => {
        await mountList()

        listFiltersLogic(TRACES_LIST_FILTERS).actions.setPropertyFilters([MODEL_FILTER])
        await settle()

        expect(requestedIds('previews').at(-1)).toEqual(['trace-e'])
        expect(requestedIds('people').at(-1)).toEqual(['trace-e'])
        expect(requestedIds('sentiment').at(-1)).toEqual(['trace-e'])
        expect([...logic.values.previews.keys()]).toEqual([...FIRST_PAGE_IDS, 'trace-e'])
    })

    it('marks the rows of a failed read as failed, without a toast, and fills the other reads and the rows', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        const captureException = jest.spyOn(posthog, 'captureException')
        answer = (read, body) => (read === 'previews' ? FAILED : answerFor(read, body.trace_ids))

        await mountList()

        expect(statuses(logic.values.previews, FIRST_PAGE_IDS)).toEqual(['error', 'error', 'error'])
        expect(statuses(logic.values.people, FIRST_PAGE_IDS)).toEqual(['ready', 'ready', 'ready'])
        expect(statuses(logic.values.sentiments, FIRST_PAGE_IDS)).toEqual(['ready', 'ready', 'ready'])
        expect(tracesListLogic.values.items.map((item) => item.id)).toEqual(FIRST_PAGE_IDS)
        expect(toastError).not.toHaveBeenCalled()
        expect(captureException).toHaveBeenCalledTimes(1)
    })

    it('asks for the failed rows again when the person steps back to their page', async () => {
        let previewsFail = true
        answer = (read, body) => (read === 'previews' && previewsFail ? FAILED : answerFor(read, body.trace_ids))
        await mountList()
        tracesListLogic.actions.showNextPage()
        await settle()
        previewsFail = false

        tracesListLogic.actions.showPreviousPage()
        await settle()

        expect(requestedIds('previews')).toEqual([FIRST_PAGE_IDS, ['trace-d'], FIRST_PAGE_IDS])
        expect(statuses(logic.values.previews, FIRST_PAGE_IDS)).toEqual(['ready', 'ready', 'ready'])
    })

    it("keeps the next page's rows loading when the previous page's read fails after it", async () => {
        const firstPageAnswer = deferred()
        answer = async (read, body) => {
            if (read === 'previews' && body.trace_ids.includes('trace-a')) {
                await firstPageAnswer.promise
                return FAILED
            }
            if (read === 'previews') {
                return new Promise(() => {})
            }
            return answerFor(read, body.trace_ids)
        }
        mount()
        await expectLogic(tracesListLogic).toDispatchActions(['loadTracesPageSuccess'])
        expect(statuses(logic.values.previews, FIRST_PAGE_IDS)).toEqual(['loading', 'loading', 'loading'])

        tracesListLogic.actions.showNextPage()
        await expectLogic(tracesListLogic).toDispatchActions(['loadTracesPageSuccess'])
        firstPageAnswer.resolve()
        await expectLogic(logic).toDispatchActions(['cellsFailed'])

        expect(statuses(logic.values.previews, [...FIRST_PAGE_IDS, 'trace-d'])).toEqual([
            'error',
            'error',
            'error',
            'loading',
        ])
    })

    it("reads the shown page's cells again on reload and keeps the old values until the answers land", async () => {
        await mountList()
        const refreshedAnswers = deferred()
        answer = async (read, body) => {
            await refreshedAnswers.promise
            return read === 'previews'
                ? [200, { items: body.trace_ids.map((id) => makeTracePreview(id, { output: 'A refreshed answer.' })) }]
                : answerFor(read, body.trace_ids)
        }

        tracesListLogic.actions.reload()
        await expectLogic(tracesListLogic).toDispatchActions(['loadTracesPageSuccess'])
        expect(logic.values.previews.get('trace-a')).toEqual(ready(makeTracePreview('trace-a')))

        refreshedAnswers.resolve()
        await settle()

        expect(requestedIds('previews')).toEqual([FIRST_PAGE_IDS, FIRST_PAGE_IDS])
        expect(requestedIds('people')).toEqual([FIRST_PAGE_IDS, FIRST_PAGE_IDS])
        expect(requestedIds('sentiment')).toEqual([FIRST_PAGE_IDS, FIRST_PAGE_IDS])
        expect(logic.values.previews.get('trace-a')).toEqual(
            ready(makeTracePreview('trace-a', { output: 'A refreshed answer.' }))
        )
    })

    it('keeps the newer values when an older read of the same rows answers last', async () => {
        await mountList()
        const olderAnswer = deferred()
        let refreshes = 0
        answer = async (read, body) => {
            if (read !== 'previews') {
                return answerFor(read, body.trace_ids)
            }
            refreshes += 1
            const isOlder = refreshes === 1
            if (isOlder) {
                await olderAnswer.promise
            }
            const output = isOlder ? 'An older answer.' : 'A newer answer.'
            return [200, { items: body.trace_ids.map((id) => makeTracePreview(id, { output })) }]
        }

        const newer = ready(makeTracePreview('trace-a', { output: 'A newer answer.' }))

        tracesListLogic.actions.reload()
        await waitFor(() => expect(requestedIds('previews')).toHaveLength(2))
        tracesListLogic.actions.reload()
        await waitFor(() => expect(logic.values.previews.get('trace-a')).toEqual(newer))
        olderAnswer.resolve()
        await settle()

        expect(requestedIds('previews')).toEqual([FIRST_PAGE_IDS, FIRST_PAGE_IDS, FIRST_PAGE_IDS])
        expect(logic.values.previews.get('trace-a')).toEqual(newer)
    })
})
