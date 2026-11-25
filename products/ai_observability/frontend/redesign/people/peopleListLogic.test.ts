import { waitFor } from '@testing-library/react'
import { getPluginContext } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { PeopleNewCountApi, PersonListApi } from '../../generated/api.schemas'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { PEOPLE_LIST_FILTERS, peopleListLogic } from './peopleListLogic'
import { PEOPLE_NEW_COUNT_URL, PEOPLE_URL, makePersonListPage } from './testFixtures'

const LIST_PATH = urls.aiObservabilityUsers()
const PAGE = makePersonListPage(['person-a', 'person-b'], { count: 120, counts: { anonymous: 2 }, lookbackDays: 45 })
const NEW_COUNT_PARAMS = { date_from: '-24h', filter_test_accounts: 'false', include_anonymous: 'false' }
const FIRST_PAGE_PARAMS = {
    date_from: '-24h',
    filter_test_accounts: 'false',
    order: 'last_seen',
    include_anonymous: 'false',
    limit: '50',
    offset: '0',
}
const MODEL_FILTER: AnyPropertyFilter = {
    key: '$ai_model',
    value: ['gpt-4'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

type Answer = [number, PersonListApi | { detail: string }]
type NewCountAnswer = [number, PeopleNewCountApi | { detail: string }]

function withPageLinks(page: PersonListApi, params: URLSearchParams): PersonListApi {
    const offset = Number(params.get('offset') ?? 0)
    const limit = Number(params.get('limit'))
    const link = (to: number): string => {
        const linked = new URLSearchParams(params)
        if (to > 0) {
            linked.set('offset', String(to))
        } else {
            linked.delete('offset')
        }
        return `http://testserver/api/projects/1/ai_observability/people/?${linked}`
    }
    return {
        ...page,
        next: offset + limit < page.count ? link(offset + limit) : null,
        previous: offset > 0 ? link(Math.max(0, offset - limit)) : null,
    }
}

describe('peopleListLogic', () => {
    let requests: Record<string, string>[] = []
    let answer: (params: URLSearchParams) => Answer
    let reads: string[] = []
    let newCountRequests: Record<string, string>[] = []
    let newCountAnswer: (params: URLSearchParams) => Promise<NewCountAnswer>
    let logic: ReturnType<typeof peopleListLogic.build>

    const ids = (): string[] => logic.values.items.map((item) => item.id)
    const filtersLogic = (): ReturnType<typeof listFiltersLogic.build> => listFiltersLogic(PEOPLE_LIST_FILTERS)
    const urlParam = (name: string): string | null => new URLSearchParams(router.values.location.search).get(name)

    async function mountAt(url: string): Promise<void> {
        router.actions.push(url)
        logic = peopleListLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        requests = []
        reads = []
        newCountRequests = []
        answer = (params) => [200, withPageLinks(PAGE, params)]
        newCountAnswer = async () => [200, { count: 4 }]
        useMocks({
            get: {
                [PEOPLE_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(Object.fromEntries(params))
                    reads.push('page')
                    return answer(params)
                },
                [PEOPLE_NEW_COUNT_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    newCountRequests.push(Object.fromEntries(params))
                    reads.push('new count')
                    return newCountAnswer(params)
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

    it("loads the first page in the shell's range without anonymous people", async () => {
        await mountAt(LIST_PATH)

        expect(requests).toEqual([FIRST_PAGE_PARAMS])
        expect(newCountRequests).toEqual([NEW_COUNT_PARAMS])
        expect(reads).toEqual(['page', 'new count'])
        expect(ids()).toEqual(['person-a', 'person-b'])
        expect(logic.values).toMatchObject({
            count: 120,
            newCount: 4,
            lookbackDays: 45,
            needsIdentification: false,
            order: 'last_seen',
            includeAnonymous: false,
            state: 'ready',
            previousPageOffset: null,
            nextPageOffset: 50,
        })
    })

    it('reads its order, anonymous switch and offset from the url once at mount', async () => {
        await mountAt(`${LIST_PATH}?order=cost&include_anonymous=true&offset=50`)

        expect(requests).toEqual([{ ...FIRST_PAGE_PARAMS, order: 'cost', include_anonymous: 'true', offset: '50' }])
        expect(logic.values).toMatchObject({ previousPageOffset: 0, nextPageOffset: 100 })
    })

    it('steps to another page and writes its offset to the url', async () => {
        await mountAt(LIST_PATH)

        logic.actions.setOffset(50)
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.at(-1)).toEqual({ ...FIRST_PAGE_PARAMS, offset: '50' })
        expect(urlParam('offset')).toEqual('50')
    })

    it.each([
        ['the order', () => logic.actions.setOrder('cost'), { order: 'cost' }, { order: 'cost' }],
        [
            'the anonymous switch',
            () => logic.actions.setIncludeAnonymous(true),
            { include_anonymous: 'true' },
            { include_anonymous: 'true' },
        ],
        [
            'a property filter',
            () => filtersLogic().actions.setPropertyFilters([MODEL_FILTER]),
            { properties: JSON.stringify([MODEL_FILTER]) },
            {},
        ],
        ['the date range', () => shellScopeLogic.actions.setDateRange('-7d', null), { date_from: '-7d' }, {}],
    ])('reads page one when %s changes, and writes it to the url', async (_name, change, params, url) => {
        await mountAt(`${LIST_PATH}?offset=50`)

        change()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.at(-1)).toEqual({ ...FIRST_PAGE_PARAMS, ...params })
        expect(urlParam('offset')).toBeNull()
        for (const [name, value] of Object.entries(url)) {
            expect(urlParam(name)).toEqual(value)
        }
    })

    it.each([
        ['the order', () => logic.actions.setOrder('cost'), () => logic.actions.setOrder('last_seen')],
        [
            'the anonymous switch',
            () => logic.actions.setIncludeAnonymous(true),
            () => logic.actions.setIncludeAnonymous(false),
        ],
        [
            'the new people view',
            () => filtersLogic().actions.toggleQuickFilter('new'),
            () => filtersLogic().actions.toggleQuickFilter('new'),
        ],
        [
            'the person search',
            () => filtersLogic().actions.setSearch('ana'),
            () => filtersLogic().actions.setSearch(''),
        ],
        [
            'a property filter',
            () => filtersLogic().actions.setPropertyFilters([MODEL_FILTER]),
            () => filtersLogic().actions.setPropertyFilters([]),
        ],
        [
            'the date range',
            () => shellScopeLogic.actions.setDateRange('-7d', null),
            () => shellScopeLogic.actions.setDateRange('-24h', null),
        ],
        [
            'the test account switch',
            () => shellScopeLogic.actions.setFilterTestAccounts(true),
            () => shellScopeLogic.actions.setFilterTestAccounts(false),
        ],
    ])('stays on page one when %s changes and changes back', async (_name, change, changeBack) => {
        await mountAt(`${LIST_PATH}?offset=50`)

        change()
        await expectLogic(logic).toFinishAllListeners()
        changeBack()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.at(-1)).toEqual(FIRST_PAGE_PARAMS)
        expect(urlParam('offset')).toBeNull()
    })

    it('restores the page of an entry that Back returns to', async () => {
        window.history.replaceState({}, '', '/')
        Object.assign(getPluginContext('router'), { history: window.history, location: window.location })
        await mountAt(`${LIST_PATH}?offset=50`)
        logic.actions.openPerson('person-a')
        logic.actions.setOrder('cost')
        await expectLogic(logic).toFinishAllListeners()
        expect(requests.at(-1)).toEqual({ ...FIRST_PAGE_PARAMS, order: 'cost' })

        window.history.back()
        await waitFor(() => expect(router.values.location.search).toEqual('?offset=50'))
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.at(-1)).toEqual({ ...FIRST_PAGE_PARAMS, offset: '50' })
        expect(urlParam('offset')).toEqual('50')
    })

    it('sends the new people view and keeps the new count without reading it again', async () => {
        await mountAt(LIST_PATH)

        filtersLogic().actions.toggleQuickFilter('new')
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.at(-1)).toEqual({ ...FIRST_PAGE_PARAMS, view: 'new' })
        expect(urlParam('view')).toEqual('new')
        expect(logic.values.newCount).toEqual(4)
        expect(newCountRequests).toHaveLength(1)
    })

    it('drops the new count of a selection the list has left', async () => {
        let releaseFirst = (): void => {}
        const firstHeld = new Promise<void>((resolve) => (releaseFirst = resolve))
        newCountAnswer = async (params) => {
            if (params.get('date_from') === '-24h') {
                await firstHeld
                return [200, { count: 9 }]
            }
            return [200, { count: 3 }]
        }
        router.actions.push(LIST_PATH)
        logic = peopleListLogic()
        logic.mount()
        await waitFor(() => expect(newCountRequests).toHaveLength(1))
        expect(logic.values.newCount).toBeNull()

        shellScopeLogic.actions.setDateRange('-7d', null)
        await waitFor(() => expect(logic.values.newCount).toEqual(3))
        releaseFirst()
        await expectLogic(logic).toFinishAllListeners()

        expect(newCountRequests.map((params) => params.date_from)).toEqual(['-24h', '-7d'])
        expect(logic.values.newCount).toEqual(3)
    })

    it('reads the new count once while pages, the order and the new people view change during its read', async () => {
        let release = (): void => {}
        const held = new Promise<void>((resolve) => (release = resolve))
        newCountAnswer = async () => {
            await held
            return [200, { count: 9 }]
        }
        router.actions.push(LIST_PATH)
        logic = peopleListLogic()
        logic.mount()
        await waitFor(() => expect(newCountRequests).toHaveLength(1))
        expect(logic.values).toMatchObject({ newCount: null, newCountLoading: true })

        logic.actions.setOffset(50)
        await waitFor(() => expect(requests).toHaveLength(2))
        logic.actions.setOrder('cost')
        await waitFor(() => expect(requests).toHaveLength(3))
        filtersLogic().actions.toggleQuickFilter('new')
        await waitFor(() => expect(requests).toHaveLength(4))
        await waitFor(() => expect(logic.values.state).toEqual('ready'))
        release()

        await waitFor(() => expect(logic.values).toMatchObject({ newCount: 9, newCountLoading: false }))
        expect(newCountRequests).toEqual([NEW_COUNT_PARAMS])
    })

    it('shows no new count while the count of a new selection loads', async () => {
        let releaseNext = (): void => {}
        const nextHeld = new Promise<void>((resolve) => (releaseNext = resolve))
        newCountAnswer = async (params) => {
            if (params.get('date_from') === '-7d') {
                await nextHeld
                return [200, { count: 3 }]
            }
            return [200, { count: 9 }]
        }
        await mountAt(LIST_PATH)
        expect(logic.values.newCount).toEqual(9)

        shellScopeLogic.actions.setDateRange('-7d', null)
        await waitFor(() => expect(newCountRequests).toHaveLength(2))
        expect(logic.values.newCount).toBeNull()
        releaseNext()

        await waitFor(() => expect(logic.values.newCount).toEqual(3))
    })

    it('shows no new count without a toast when its read fails, and keeps the rows', async () => {
        silenceKeaLoadersErrors()
        const toastError = jest.spyOn(lemonToast, 'error')
        newCountAnswer = async () => [500, { detail: 'boom' }]

        await mountAt(LIST_PATH)

        expect(logic.values).toMatchObject({ newCount: null, newCountLoading: false, state: 'ready' })
        expect(toastError).not.toHaveBeenCalled()
    })

    it('sends a person search once typing settles, as person_search', async () => {
        await mountAt(LIST_PATH)

        logic.actions.setPersonSearch('ana@')
        expect(logic.values.personSearch).toEqual('ana@')
        expect(requests).toHaveLength(1)
        await expectLogic(filtersLogic()).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests.at(-1)).toEqual({ ...FIRST_PAGE_PARAMS, person_search: 'ana@' })
        expect(urlParam('person_search')).toEqual('ana@')
    })

    it.each([
        ['every person in range is anonymous', '', { needsIdentification: true }, 'empty', true],
        ['nothing narrows the list', '', {}, 'empty', false],
        ['a person search is on', 'person_search=ana', {}, 'empty-filtered', false],
        ['the new people view is on', 'view=new', {}, 'empty-filtered', false],
        [
            'a property filter is on',
            `filters=${encodeURIComponent(JSON.stringify([MODEL_FILTER]))}`,
            {},
            'empty-filtered',
            false,
        ],
    ])('shows an empty list when %s', async (_name, query, overrides, state, needsIdentification) => {
        answer = () => [200, makePersonListPage([], overrides)]

        await mountAt(`${LIST_PATH}?${query}`)

        expect(logic.values).toMatchObject({ state, needsIdentification })
    })

    it('shows the error without a toast when the first page fails', async () => {
        silenceKeaLoadersErrors()
        const toastError = jest.spyOn(lemonToast, 'error')
        answer = () => [500, { detail: 'boom' }]

        await mountAt(LIST_PATH)

        expect(logic.values).toMatchObject({ items: [], state: 'error' })
        expect(toastError).not.toHaveBeenCalled()
    })

    it('keeps the rows and toasts once when a reload fails', async () => {
        silenceKeaLoadersErrors()
        const toastError = jest.spyOn(lemonToast, 'error')
        await mountAt(LIST_PATH)
        answer = () => [500, { detail: 'boom' }]

        logic.actions.reload()
        await expectLogic(logic).toFinishAllListeners()

        expect(ids()).toEqual(['person-a', 'person-b'])
        expect(logic.values.state).toEqual('ready')
        expect(toastError).toHaveBeenCalledTimes(1)
    })

    it("keeps the open person from the url across a reload, and opens another on click without the first one's trace", async () => {
        await mountAt(`${LIST_PATH}?person=person-b&trace=trace-1&ts=2026-11-24T16:40:00Z`)
        expect(logic.values.openPersonId).toEqual('person-b')

        logic.actions.reload()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.openPersonId).toEqual('person-b')

        logic.actions.openPerson('person-a')
        expect(urlParam('person')).toEqual('person-a')
        expect([urlParam('trace'), urlParam('ts')]).toEqual([null, null])
        expect(logic.values.openPersonId).toEqual('person-a')
        expect(requests).toHaveLength(2)

        logic.actions.openPerson(null)
        expect(logic.values.openPersonId).toBeNull()
    })

    it('tracks each loaded page and each failure', async () => {
        silenceKeaLoadersErrors()
        const capture = jest.spyOn(posthog, 'capture')
        await mountAt(LIST_PATH)
        answer = () => [500, { detail: 'boom' }]
        logic.actions.setIncludeAnonymous(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(capture.mock.calls.filter(([event]) => event.startsWith('llma people list'))).toEqual([
            [
                'llma people list loaded',
                { count: 120, order: 'last_seen', include_anonymous: false, load_ms: expect.any(Number) },
            ],
            ['llma people list failed', { order: 'last_seen', include_anonymous: true }],
        ])
    })
})
