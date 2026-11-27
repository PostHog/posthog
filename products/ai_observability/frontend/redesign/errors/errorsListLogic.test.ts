import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { type ErrorListApi, ErrorOrderApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { ERRORS_LIST_FILTERS, errorsListLogic } from './errorsListLogic'
import { ERRORS_URL, makeErrorListPage } from './testFixtures'

const LIST_PATH = urls.aiObservabilityErrors()
const COUNTS = { total: 120, increasing: 4, decreasing: 2, maxOccurrences: 128 }
const PAGE_PARAMS = { date_from: '-7d', filter_test_accounts: 'false', limit: '50', offset: '0' }
const MODEL_FILTER: AnyPropertyFilter = {
    key: '$ai_model',
    value: ['example-model'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}
const RANGE_TOO_LONG = { code: 'range_too_long', detail: 'Pick a range of 90 days or less.' }

type Answer = [number, ErrorListApi | Record<string, string>]

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve = (): void => {}
    const promise = new Promise<void>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

function pageAt(params: URLSearchParams): ErrorListApi {
    const offset = Number(params.get('offset'))
    const order = Object.values(ErrorOrderApi).find((value) => value === params.get('order')) ?? 'occurrences'
    return makeErrorListPage([`error-${offset}`, `error-${offset + 1}`], { count: COUNTS.total, counts: COUNTS, order })
}

describe('errorsListLogic', () => {
    let requests: Record<string, string>[] = []
    let answer: (params: URLSearchParams) => Answer | Promise<Answer>
    let logic: ReturnType<typeof errorsListLogic.build>

    const keys = (): string[] => logic.values.items.map((item) => item.key)
    const filtersLogic = (): ReturnType<typeof listFiltersLogic.build> => listFiltersLogic(ERRORS_LIST_FILTERS)

    async function mountAt(url: string): Promise<void> {
        router.actions.push(url)
        logic = errorsListLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        requests = []
        answer = (params) => [200, pageAt(params)]
        useMocks({
            get: {
                [ERRORS_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(Object.fromEntries(params))
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

    it('loads the first page of the last seven days with no order and its counts', async () => {
        await mountAt(LIST_PATH)

        expect(requests).toEqual([PAGE_PARAMS])
        expect(keys()).toEqual(['error-0', 'error-1'])
        expect(logic.values).toMatchObject({
            counts: COUNTS,
            count: COUNTS.total,
            order: null,
            pageIndex: 0,
            state: 'ready',
            canShowNext: true,
            canShowPrevious: false,
        })
    })

    it.each([
        [
            'the search, view, order and filters',
            `error_search=timeout&view=increasing&order=users&filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}`,
            { search: 'timeout', view: 'increasing', order: 'users', properties: JSON.stringify([MODEL_FILTER]) },
        ],
        ['the order by its api value', 'order=last_seen', { order: 'last_seen' }],
        ['no order for an order the api does not know', 'order=calls', {}],
        ['no view for a view the api does not know', 'view=failing', {}],
        [
            'the range and the test accounts switch',
            'date_from=-24h&filter_test_accounts=true',
            { date_from: '-24h', filter_test_accounts: 'true' },
        ],
    ])('reads once from the url at mount: %s', async (_name, query, params) => {
        await mountAt(`${LIST_PATH}?${query}`)

        expect(requests).toEqual([{ ...PAGE_PARAMS, ...params }])
    })

    it('reads the page at its offset and keeps the rows on screen while it loads', async () => {
        await mountAt(LIST_PATH)
        const held = deferred()
        answer = async (params) => {
            await held.promise
            return [200, pageAt(params)]
        }

        logic.actions.setPageIndex(2)
        expect(logic.values).toMatchObject({ pageIndex: 0, refreshing: true, state: 'ready', canShowNext: false })
        expect(keys()).toEqual(['error-0', 'error-1'])

        held.resolve()
        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual({ ...PAGE_PARAMS, offset: '100' })
        expect(keys()).toEqual(['error-100', 'error-101'])
        expect(logic.values).toMatchObject({
            pageIndex: 2,
            refreshing: false,
            canShowPrevious: true,
            canShowNext: false,
        })
    })

    it.each([
        [
            'a filter',
            () => filtersLogic().actions.setPropertyFilters([MODEL_FILTER]),
            { properties: JSON.stringify([MODEL_FILTER]) },
        ],
        ['the search', () => filtersLogic().actions.setSearch('timeout'), { search: 'timeout' }],
        ['a quick filter', () => filtersLogic().actions.toggleQuickFilter('new'), { view: 'new' }],
        ['the order', () => logic.actions.setOrder('change'), { order: 'change' }],
        ['the date range', () => shellScopeLogic.actions.setDateRange('-24h', null), { date_from: '-24h' }],
        [
            "the shell's test accounts switch",
            () => shellScopeLogic.actions.setFilterTestAccounts(true),
            { filter_test_accounts: 'true' },
        ],
    ])('goes back to page one when %s changes', async (_name, change, params) => {
        await mountAt(LIST_PATH)
        logic.actions.setPageIndex(1)
        await expectLogic(logic).toFinishAllListeners()

        change()
        expect(logic.values).toMatchObject({ items: [], state: 'loading', pageIndex: 0 })

        await expectLogic(logic).toFinishAllListeners()
        expect(requests.slice(2)).toEqual([{ ...PAGE_PARAMS, ...params }])
        expect(keys()).toEqual(['error-0', 'error-1'])
    })

    it('sorts by no column before the first page, then by the order the api last applied until one is chosen', async () => {
        const held = deferred()
        answer = async (params) => {
            await held.promise
            return [200, pageAt(params)]
        }
        router.actions.push(LIST_PATH)
        logic = errorsListLogic()
        logic.mount()
        expect(logic.values.sortedBy).toBeNull()

        held.resolve()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.sortedBy).toEqual('occurrences')

        const reloading = deferred()
        answer = async (params) => {
            await reloading.promise
            return [200, pageAt(params)]
        }
        filtersLogic().actions.setSearch('timeout')
        expect(logic.values).toMatchObject({ state: 'loading', sortedBy: 'occurrences' })
        reloading.resolve()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setOrder('traces')
        expect(logic.values.sortedBy).toEqual('traces')
    })

    it('writes the order to the url and keeps the other params', async () => {
        await mountAt(`${LIST_PATH}?error_search=timeout`)

        logic.actions.setOrder('traces')

        expect(router.values.searchParams).toMatchObject({ error_search: 'timeout', order: 'traces' })
    })

    it('reads the order again when the url changes it', async () => {
        await mountAt(LIST_PATH)

        router.actions.push(LIST_PATH, { order: 'users' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.order).toEqual('users')
        expect(requests.at(-1)).toEqual({ ...PAGE_PARAMS, order: 'users' })
    })

    it('reloads the page on screen', async () => {
        await mountAt(LIST_PATH)
        logic.actions.setPageIndex(1)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.reload()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.slice(1)).toEqual([
            { ...PAGE_PARAMS, offset: '50' },
            { ...PAGE_PARAMS, offset: '50' },
        ])
    })

    it('drops a slow page that answers after the filters changed', async () => {
        await mountAt(LIST_PATH)
        const slowPage = deferred()
        answer = async (params) => {
            if (params.get('offset') === '50') {
                await slowPage.promise
                return [200, makeErrorListPage(['stale'])]
            }
            return [200, pageAt(params)]
        }

        logic.actions.setPageIndex(1)
        filtersLogic().actions.setPropertyFilters([MODEL_FILTER])
        await expectLogic(logic).toDispatchActions(['loadErrorsPageSuccess'])
        slowPage.resolve()
        await expectLogic(logic).toFinishAllListeners()

        expect(keys()).toEqual(['error-0', 'error-1'])
        expect(logic.values.pageIndex).toEqual(0)
    })

    it.each([
        ['nothing narrows the selection', '', false, 'empty'],
        ['a filter is on', `filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}`, false, 'empty-filtered'],
        ['a search is on', 'error_search=timeout', false, 'empty-filtered'],
        ['a quick filter is on', 'view=new', false, 'empty-filtered'],
        ['test accounts are filtered out', 'filter_test_accounts=true', false, 'empty-filtered'],
        ['nothing was ever captured, even with a search on', 'error_search=timeout', true, 'empty'],
    ])('shows an empty first page when %s', async (_name, query, nothingCaptured, state) => {
        answer = () => [200, makeErrorListPage([], { nothingCaptured })]

        await mountAt(`${LIST_PATH}?${query}`)

        expect(logic.values).toMatchObject({ state, nothingCaptured })
    })

    it.each<[string, Answer, string | null, unknown[]]>([
        ['a range that is too long', [422, RANGE_TOO_LONG], RANGE_TOO_LONG.detail, []],
        [
            'any other failure',
            [500, { detail: 'boom' }],
            null,
            [['llma diagnostics read failed', { kind: 'error', read: 'list' }]],
        ],
    ])(
        'shows the error state for %s and tracks only a failed read',
        async (_name, failed, rangeTooLongDetail, events) => {
            silenceKeaLoadersErrors()
            const capture = jest.spyOn(posthog, 'capture')
            const toastError = jest.spyOn(lemonToast, 'error')
            answer = () => failed

            await mountAt(LIST_PATH)

            expect(logic.values).toMatchObject({ items: [], state: 'error', rangeTooLongDetail })
            expect(capture.mock.calls.filter(([event]) => event.startsWith('llma diagnostics'))).toEqual(events)
            expect(toastError).not.toHaveBeenCalled()
        }
    )

    it('keeps the rows and toasts once when another page fails', async () => {
        silenceKeaLoadersErrors()
        const toastError = jest.spyOn(lemonToast, 'error')
        await mountAt(LIST_PATH)
        answer = () => [500, { detail: 'boom' }]

        logic.actions.setPageIndex(1)
        await expectLogic(logic).toFinishAllListeners()

        expect(keys()).toEqual(['error-0', 'error-1'])
        expect(logic.values).toMatchObject({ state: 'ready', pageIndex: 0 })
        expect(toastError).toHaveBeenCalledTimes(1)
    })
})
