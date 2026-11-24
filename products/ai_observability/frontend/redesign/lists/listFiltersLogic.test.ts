import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { pageLoad } from '../shared/testPageLoad'
import { currentUrlWith } from '../trace/rawSearchParam'
import { LIST_SEARCH_DEBOUNCE_MS, ListFilters, listFiltersLogic } from './listFiltersLogic'

const LIST_PATH = urls.aiObservabilityTraces()
const MODEL_FILTER: AnyPropertyFilter = {
    key: '$ai_model',
    value: ['gpt-4'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}
const NO_FILTERS: ListFilters = { propertyFilters: [], search: '', quickFilter: null }

describe('listFiltersLogic', () => {
    let logic: ReturnType<typeof listFiltersLogic.build>

    const param = (name: string): string | null => new URLSearchParams(router.values.location.search).get(name)

    function mountAt(url: string): void {
        router.actions.locationChanged(pageLoad(url))
        logic = listFiltersLogic({ listId: 'traces', path: LIST_PATH })
        logic.mount()
    }

    function type(...drafts: string[]): void {
        jest.useFakeTimers()
        for (const draft of drafts) {
            logic.actions.setSearchDraft(draft)
        }
    }

    async function waitOutDebounce(): Promise<void> {
        jest.advanceTimersByTime(LIST_SEARCH_DEBOUNCE_MS)
        jest.useRealTimers()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it.each<[string, string, Partial<ListFilters>, (filters: typeof logic) => Promise<void> | void]>([
        [
            'filters',
            JSON.stringify([MODEL_FILTER]),
            { propertyFilters: [MODEL_FILTER] },
            (l) => l.actions.setPropertyFilters([MODEL_FILTER]),
        ],
        [
            'trace_search',
            '1.50',
            { search: '1.50' },
            async () => {
                type('1.50')
                await waitOutDebounce()
            },
        ],
        ['view', 'errors', { quickFilter: 'errors' }, (l) => l.actions.toggleQuickFilter('errors')],
    ])('reads %s from the url and writes it back', async (name, value, filters, write) => {
        mountAt(`${LIST_PATH}?${name}=${encodeURIComponent(value)}`)
        expect(logic.values.filters).toEqual({ ...NO_FILTERS, ...filters })

        router.actions.push(LIST_PATH)
        expect(logic.values.filters).toEqual(NO_FILTERS)

        await write(logic)

        expect(logic.values.filters).toEqual({ ...NO_FILTERS, ...filters })
        expect(param(name)).toEqual(value)
        expect(router.values.lastMethod).toEqual('REPLACE')
    })

    it.each([
        ['a value that is not json', 'filters=not-json'],
        ['json that is not a list', `filters=${encodeURIComponent('{"key":"$ai_model"}')}`],
        ['a list that holds no property filters', `filters=${encodeURIComponent('[1,2]')}`],
        ['a test account value that is not a boolean', 'filter_test_accounts=maybe'],
    ])('treats %s as absent', (_name, query) => {
        mountAt(`${LIST_PATH}?${query}`)

        expect(logic.values.filters).toEqual(NO_FILTERS)
    })

    it('fills the search box from the url on load', () => {
        mountAt(`${LIST_PATH}?trace_search=invoice`)

        expect(logic.values).toMatchObject({ searchDraft: 'invoice', filters: { ...NO_FILTERS, search: 'invoice' } })
    })

    it('clears the quick filter when the same one is picked again', () => {
        mountAt(LIST_PATH)

        logic.actions.toggleQuickFilter('errors')
        logic.actions.toggleQuickFilter('errors')

        expect(logic.values.filters.quickFilter).toBeNull()
        expect(param('view')).toBeNull()
    })

    it('applies the search once the typing settles', async () => {
        mountAt(LIST_PATH)
        const { filters } = logic.values

        type('in', 'inv', 'invoice')
        expect(logic.values).toMatchObject({ searchDraft: 'invoice', filters })
        expect(param('trace_search')).toBeNull()
        await waitOutDebounce()

        expect(logic.values.filters).toEqual({ ...NO_FILTERS, search: 'invoice' })
        expect(param('trace_search')).toEqual('invoice')
    })

    it('applies the typed search with a filter change in one update', async () => {
        mountAt(LIST_PATH)
        type('invoice')

        logic.actions.toggleQuickFilter('errors')
        const { filters } = logic.values
        await waitOutDebounce()

        expect(filters).toEqual({ ...NO_FILTERS, search: 'invoice', quickFilter: 'errors' })
        expect(logic.values.filters).toBe(filters)
        expect(router.values.searchParams).toEqual({ trace_search: 'invoice', view: 'errors' })
    })

    it('changes nothing when only the trace drawer params change', async () => {
        mountAt(`${LIST_PATH}?view=errors&filter_test_accounts=true&trace_search=1.50`)
        const { filters } = logic.values
        type('invoice')

        router.actions.push(...currentUrlWith(router.values, { trace: 'abc', ts: '2026-01-01T12:00:00Z' }))
        router.actions.replace(...currentUrlWith(router.values, { step: 'step-1' }))

        expect(logic.values).toMatchObject({ searchDraft: 'invoice' })
        expect(logic.values.filters).toBe(filters)
        await waitOutDebounce()
        expect(logic.values.filters.search).toEqual('invoice')
        expect(param('trace')).toEqual('abc')
    })

    it('ignores the url of another path and leaves it alone', () => {
        mountAt(LIST_PATH)
        const errorsUrl = `${urls.aiObservabilityErrors()}?view=errors&trace_search=invoice`

        router.actions.push(errorsUrl)
        logic.actions.setPropertyFilters([MODEL_FILTER])

        expect(logic.values.filters).toEqual({ ...NO_FILTERS, propertyFilters: [MODEL_FILTER] })
        expect(router.values.location.pathname).toContain(urls.aiObservabilityErrors())
        expect(router.values.searchParams).toEqual({ view: 'errors', trace_search: 'invoice' })
    })

    it('clears the three filters, the typed search and their params, and keeps the others', () => {
        const filters = encodeURIComponent(JSON.stringify([MODEL_FILTER]))
        mountAt(
            `${LIST_PATH}?filters=${filters}&filter_test_accounts=true&trace_search=invoice&view=errors&date_from=-7d`
        )

        logic.actions.resetFilters()

        expect(logic.values).toMatchObject({ filters: NO_FILTERS, searchDraft: '' })
        expect(router.values.searchParams).toEqual({ date_from: '-7d', filter_test_accounts: 'true' })
    })
})
