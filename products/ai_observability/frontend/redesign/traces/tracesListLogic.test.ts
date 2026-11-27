import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { TraceListApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { makeTraceListPage } from './testFixtures'
import { TRACES_LIST_FILTERS, tracesListLogic } from './tracesListLogic'

const TRACES_URL = '/api/projects/:team_id/ai_observability/traces/'
const LIST_PATH = urls.aiObservabilityTraces()
const COUNTS = { total: 3, errors: 1, feedback: 0 }
const FIRST_PAGE = makeTraceListPage(['trace-a', 'trace-b'], { counts: COUNTS, nextCursor: 'cursor-2' })
const SECOND_PAGE = makeTraceListPage(['trace-c'])
const FIRST_PAGE_PARAMS = { date_from: '-7d', filter_test_accounts: 'false', limit: '50' }
const SEARCH_FLAG = FEATURE_FLAGS.LLM_OBSERVABILITY_TRACE_SEARCH
const MODEL_FILTER: AnyPropertyFilter = {
    key: '$ai_model',
    value: ['gpt-4'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

type Answer = [number, TraceListApi | { detail: string }]

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

describe('tracesListLogic', () => {
    let requests: Record<string, string>[] = []
    let signals: AbortSignal[] = []
    let answer: (params: URLSearchParams) => Answer | Promise<Answer>
    let logic: ReturnType<typeof tracesListLogic.build>

    const ids = (): string[] => logic.values.items.map((item) => item.id)
    const filtersLogic = (): ReturnType<typeof listFiltersLogic.build> => listFiltersLogic(TRACES_LIST_FILTERS)

    async function mountAt(url: string, flags: string[] = []): Promise<void> {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        router.actions.push(url)
        logic = tracesListLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        requests = []
        signals = []
        answer = (params) => [200, params.get('cursor') === 'cursor-2' ? SECOND_PAGE : FIRST_PAGE]
        useMocks({
            get: {
                [TRACES_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(Object.fromEntries(params))
                    signals.push(request.signal)
                    return answer(params)
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
    })

    it('loads the first page of the last seven days with its counts', async () => {
        await mountAt(LIST_PATH)

        expect(requests).toEqual([FIRST_PAGE_PARAMS])
        expect(ids()).toEqual(['trace-a', 'trace-b'])
        expect(logic.values).toMatchObject({
            counts: COUNTS,
            state: 'ready',
            canShowNext: true,
            canShowPrevious: false,
        })
    })

    it('reads once from the filters in the url at mount', async () => {
        await mountAt(`${LIST_PATH}?filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}&view=errors`)

        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, properties: JSON.stringify([MODEL_FILTER]), view: 'errors' }])
    })

    it('sends the first scope in the url it accepts', async () => {
        await mountAt(`${LIST_PATH}?tool=search_docs&person=p1`)

        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, person_id: 'p1' }])
    })

    it('drops the pages and reads page one without the scope once it is cleared', async () => {
        await mountAt(`${LIST_PATH}?error=a%25b%0Ac`)
        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, error: 'a%b\nc' }])
        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()

        filtersLogic().actions.clearScope()
        expect(logic.values).toMatchObject({ items: [], state: 'loading', pageIndex: 0 })

        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual(FIRST_PAGE_PARAMS)
        expect(router.values.location.search).toEqual('')
    })

    it('reads a page it has not shown yet and keeps the pages it has', async () => {
        await mountAt(LIST_PATH)

        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()
        expect(requests[1]).toEqual({ ...FIRST_PAGE_PARAMS, cursor: 'cursor-2' })
        expect(ids()).toEqual(['trace-c'])
        expect(logic.values).toMatchObject({ counts: COUNTS, canShowNext: false, canShowPrevious: true })

        logic.actions.showPreviousPage()
        expect(ids()).toEqual(['trace-a', 'trace-b'])

        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()
        expect(ids()).toEqual(['trace-c'])
        expect(requests).toHaveLength(2)
    })

    it.each([
        [
            'a filter',
            () => filtersLogic().actions.setPropertyFilters([MODEL_FILTER]),
            { ...FIRST_PAGE_PARAMS, properties: JSON.stringify([MODEL_FILTER]) },
        ],
        [
            'the date range',
            () => shellScopeLogic.actions.setDateRange('-24h', null),
            { ...FIRST_PAGE_PARAMS, date_from: '-24h' },
        ],
        [
            "the shell's test accounts switch",
            () => shellScopeLogic.actions.setFilterTestAccounts(true),
            { ...FIRST_PAGE_PARAMS, filter_test_accounts: 'true' },
        ],
    ])('drops the pages and reads page one when %s changes', async (_name, change, params) => {
        await mountAt(LIST_PATH)
        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()

        change()
        expect(logic.values).toMatchObject({ items: [], state: 'loading', pageIndex: 0 })

        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual(params)
        expect(ids()).toEqual(['trace-a', 'trace-b'])
    })

    it.each([
        ['sends', [SEARCH_FLAG], { search: 'invoice' }],
        ['leaves out', [], {}],
    ])('%s the search in the url by the search flag', async (_name, flags, search) => {
        await mountAt(`${LIST_PATH}?trace_search=invoice`, flags)

        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, ...search }])
    })

    it('reads the next page with the first page params, not a search still being typed', async () => {
        await mountAt(LIST_PATH, [SEARCH_FLAG])

        filtersLogic().actions.setSearchDraft('refund')
        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests[1]).toEqual({ ...FIRST_PAGE_PARAMS, cursor: 'cursor-2' })
    })

    it('drops a slow answer for the filters before a change', async () => {
        const slowAnswer = deferred()
        answer = async (params) => {
            if (!params.has('properties')) {
                await slowAnswer.promise
                return [200, makeTraceListPage(['stale'])]
            }
            return [200, makeTraceListPage(['filtered'])]
        }
        router.actions.push(LIST_PATH)
        logic = tracesListLogic()
        logic.mount()

        filtersLogic().actions.setPropertyFilters([MODEL_FILTER])
        await expectLogic(logic).toDispatchActions(['loadTracesPageSuccess'])
        slowAnswer.resolve()
        await expectLogic(logic).toFinishAllListeners()

        expect(ids()).toEqual(['filtered'])
    })

    it('aborts a read that a newer selection supersedes, and the read in flight on unmount', async () => {
        const held = deferred()
        answer = async () => {
            await held.promise
            return [200, FIRST_PAGE]
        }
        router.actions.push(LIST_PATH)
        logic = tracesListLogic()
        logic.mount()

        filtersLogic().actions.setPropertyFilters([MODEL_FILTER])
        await waitFor(() => expect(signals).toHaveLength(2))
        expect(signals.map((signal) => signal.aborted)).toEqual([true, false])

        logic.unmount()
        expect(signals[1].aborted).toBe(true)

        held.resolve()
    })

    it('drops a slow next page that answers after the filters changed', async () => {
        const slowNextPage = deferred()
        answer = async (params) => {
            if (params.has('cursor')) {
                await slowNextPage.promise
                return [200, SECOND_PAGE]
            }
            return [200, params.has('properties') ? makeTraceListPage(['filtered']) : FIRST_PAGE]
        }
        await mountAt(LIST_PATH)

        logic.actions.showNextPage()
        filtersLogic().actions.setPropertyFilters([MODEL_FILTER])
        await expectLogic(logic).toDispatchActions(['loadTracesPageSuccess'])
        slowNextPage.resolve()
        await expectLogic(logic).toFinishAllListeners()

        expect(ids()).toEqual(['filtered'])
        expect(logic.values.pageIndex).toEqual(0)
    })

    it('holds Previous while a next page loads', async () => {
        const slowNextPage = deferred()
        answer = async (params) => {
            if (params.get('cursor') === 'cursor-3') {
                await slowNextPage.promise
                return [200, makeTraceListPage(['trace-d'])]
            }
            return [200, params.has('cursor') ? { ...SECOND_PAGE, nextCursor: 'cursor-3' } : FIRST_PAGE]
        }
        await mountAt(LIST_PATH)
        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.showNextPage()
        expect(logic.values.canShowPrevious).toBe(false)
        logic.actions.showPreviousPage()
        slowNextPage.resolve()
        await expectLogic(logic).toFinishAllListeners()

        expect(ids()).toEqual(['trace-d'])
        expect(logic.values).toMatchObject({ pageIndex: 2, canShowPrevious: true })
    })

    it('shows the error when the first page fails with nothing on screen', async () => {
        silenceKeaLoadersErrors()
        const toastError = jest.spyOn(lemonToast, 'error')
        answer = () => [500, { detail: 'boom' }]

        await mountAt(LIST_PATH)

        expect(logic.values).toMatchObject({ items: [], state: 'error' })
        expect(toastError).not.toHaveBeenCalled()
    })

    it.each([
        ['a reload', () => logic.actions.reload()],
        ['the next page', () => logic.actions.showNextPage()],
    ])('keeps the rows and the page and toasts once when %s fails', async (_name, read) => {
        silenceKeaLoadersErrors()
        const toastError = jest.spyOn(lemonToast, 'error')
        await mountAt(LIST_PATH)
        answer = () => [500, { detail: 'boom' }]

        read()
        await expectLogic(logic).toFinishAllListeners()

        expect(ids()).toEqual(['trace-a', 'trace-b'])
        expect(logic.values).toMatchObject({ state: 'ready', pageIndex: 0 })
        expect(toastError).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['nothing narrows the selection', '', 'empty'],
        ['a property filter is on', `filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}`, 'empty-filtered'],
        ['a search is on', 'trace_search=invoice', 'empty-filtered'],
        ['a quick filter is on', 'view=errors', 'empty-filtered'],
        ['test accounts are filtered out', 'filter_test_accounts=true', 'empty-filtered'],
        ['a scope is on', 'tool=search_docs', 'empty-filtered'],
    ])('shows an empty first page as %s', async (_name, query, state) => {
        answer = () => [200, makeTraceListPage([])]

        await mountAt(`${LIST_PATH}?${query}`, [SEARCH_FLAG])

        expect(logic.values.state).toEqual(state)
    })

    it("sends the shell's filterTestAccounts", async () => {
        await mountAt(`${LIST_PATH}?filter_test_accounts=true`)

        expect(logic.values.filterTestAccounts).toBe(true)
        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, filter_test_accounts: 'true' }])
    })

    it('tracks each first page once with its row count', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        await mountAt(LIST_PATH)
        logic.actions.showNextPage()
        await expectLogic(logic).toFinishAllListeners()

        expect(capture.mock.calls.filter(([event]) => event === 'llma traces list loaded')).toEqual([
            [
                'llma traces list loaded',
                {
                    rows_wait_ms: expect.any(Number),
                    row_count: 2,
                    date_from: '-7d',
                    quick_filter: null,
                    searched: false,
                },
            ],
        ])
    })
})
