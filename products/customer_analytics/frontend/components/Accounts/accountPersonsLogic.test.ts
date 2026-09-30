import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'
import { PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { accountsPersonsList } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountPersonApi,
    AccountPersonsResponseApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNT_PERSONS_PAGE_SIZE, MAX_PERSON_PROPERTY_COLUMNS } from './accountPersons'
import { ACCOUNT_PERSONS_READ_SOURCE, accountPersonsLogic, type AccountPersonsLogicProps } from './accountPersonsLogic'
import { AccountsEvents } from './constants'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsPersonsList: jest.fn(),
}))
jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn() }))

const mockList = accountsPersonsList as jest.MockedFunction<typeof accountsPersonsList>
const mockCopy = copyToClipboard as jest.MockedFunction<typeof copyToClipboard>

const DEFAULT_PARAMS = {
    limit: ACCOUNT_PERSONS_PAGE_SIZE,
    offset: 0,
    order_by: '-account_last_seen',
    select: '["email"]',
}

const person = (id: string, email: string | null = `${id}@example.com`): AccountPersonApi => ({
    id,
    name: id,
    distinct_ids: [`distinct-${id}`],
    properties: email === null ? {} : { email },
    account_first_seen: '2025-01-02T03:04:05Z',
    account_last_seen: '2026-01-02T03:04:05Z',
})

const pageOf = (persons: AccountPersonApi[], hasMore = false, offset = 0): AccountPersonsResponseApi => ({
    results: persons,
    limit: ACCOUNT_PERSONS_PAGE_SIZE,
    offset,
    has_more: hasMore,
    membership_ready: true,
})

const planFilter = (overrides: Partial<PersonPropertyFilter> = {}): PersonPropertyFilter => ({
    type: PropertyFilterType.Person,
    key: 'plan',
    operator: PropertyOperator.Exact,
    value: ['pro'],
    ...overrides,
})

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((res) => {
        resolve = res
    })
    return { promise, resolve }
}

describe('accountPersonsLogic', () => {
    let logic: ReturnType<typeof accountPersonsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
        mockList.mockResolvedValue(pageOf([person('a')]))
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mount = async (props: Partial<AccountPersonsLogicProps> = {}): Promise<void> => {
        logic = accountPersonsLogic({ accountId: 'acc-1', ...props })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('request and response', () => {
        it('loads the first page for the account with the default order and the email column', async () => {
            await mount()

            expect(mockList).toHaveBeenCalledTimes(1)
            expect(mockList).toHaveBeenCalledWith(expect.any(String), 'acc-1', DEFAULT_PARAMS)
            expect(logic.values.persons).toEqual([person('a')])
            expect(logic.values.viewState).toBe('loaded')
        })

        it('does not load without an account id', async () => {
            await mount({ accountId: '' })

            expect(mockList).not.toHaveBeenCalled()
        })

        it('keeps state separate per account', async () => {
            await mount()
            const other = accountPersonsLogic({ accountId: 'acc-2' })
            other.mount()

            other.actions.setSearchTerm('x')

            expect(other.values.searchTerm).toBe('x')
            expect(logic.values.searchTerm).toBe('')
            other.unmount()
        })

        it('lets the latest request win when an older one resolves last', async () => {
            const first = deferred<AccountPersonsResponseApi>()
            mockList.mockReturnValueOnce(first.promise)
            logic = accountPersonsLogic({ accountId: 'acc-1' })
            logic.mount()
            mockList.mockResolvedValueOnce(pageOf([person('page-2')], false, 20))

            logic.actions.setPage(2)
            await expectLogic(logic).toDispatchActions(['loadPersonsSuccess'])
            first.resolve(pageOf([person('stale')]))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.persons.map((p) => p.id)).toEqual(['page-2'])
        })
    })

    describe('search', () => {
        it('resets to the first page and sends the trimmed search after the debounce', async () => {
            mockList.mockResolvedValue(pageOf([person('a')], true))
            await mount()
            logic.actions.setPage(3)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSearchTerm('  ada@example.com ')
            expect(logic.values.page).toBe(1)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
                ...DEFAULT_PARAMS,
                search: 'ada@example.com',
            })
        })

        it('sends one request for a burst of keystrokes and never captures the raw text', async () => {
            await mount()
            mockList.mockClear()

            logic.actions.setSearchTerm('a')
            logic.actions.setSearchTerm('ad')
            logic.actions.setSearchTerm('ada')
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenCalledTimes(1)
            expect(posthog.capture).toHaveBeenCalledWith(AccountsEvents.RelatedUsersSearched, {
                has_query: true,
                query_length: 3,
                read_source: ACCOUNT_PERSONS_READ_SOURCE,
            })
        })

        it('starts from a saved search term', async () => {
            await mount({ initialConfig: { searchTerm: 'saved' } })

            expect(mockList).toHaveBeenCalledWith(expect.any(String), 'acc-1', { ...DEFAULT_PARAMS, search: 'saved' })
        })
    })

    describe('property filters', () => {
        it('ignores half-built filters, then sends the complete set as JSON and resets the page', async () => {
            await mount()
            logic.actions.setPage(2)
            await expectLogic(logic).toFinishAllListeners()
            mockList.mockClear()

            logic.actions.setPropertyFilters([planFilter({ value: undefined })])
            await expectLogic(logic).toFinishAllListeners()
            expect(mockList).not.toHaveBeenCalled()
            expect(logic.values.page).toBe(2)

            logic.actions.setPropertyFilters([planFilter()])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.page).toBe(1)
            expect(mockList).toHaveBeenCalledTimes(1)
            expect(mockList).toHaveBeenCalledWith(expect.any(String), 'acc-1', {
                ...DEFAULT_PARAMS,
                properties: JSON.stringify([planFilter()]),
            })
            expect(posthog.capture).toHaveBeenCalledWith(AccountsEvents.RelatedUsersPropertyFiltered, {
                filter_count: 1,
                is_cleared: false,
                read_source: ACCOUNT_PERSONS_READ_SOURCE,
            })
        })

        it('treats is set as complete without a value', async () => {
            await mount()

            logic.actions.setPropertyFilters([
                { type: PropertyFilterType.Person, key: 'plan', operator: PropertyOperator.IsSet },
            ] as PersonPropertyFilter[])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.activeFilters).toHaveLength(1)
        })

        it('does not reload when an edit leaves the usable filters unchanged', async () => {
            await mount()
            logic.actions.setPropertyFilters([planFilter()])
            await expectLogic(logic).toFinishAllListeners()
            mockList.mockClear()

            logic.actions.setPropertyFilters([planFilter(), planFilter({ value: undefined })])
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).not.toHaveBeenCalled()
        })

        it('drops the properties param once filters are cleared', async () => {
            await mount()
            logic.actions.setPropertyFilters([planFilter()])
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setPropertyFilters([])
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', DEFAULT_PARAMS)
        })
    })

    describe('sorting', () => {
        it.each([
            [{ columnKey: 'account_first_seen', order: 1 as const }, 'account_first_seen'],
            [{ columnKey: 'account_last_seen', order: -1 as const }, '-account_last_seen'],
            [{ columnKey: 'property:email', order: 1 as const }, 'email'],
        ])('sends %j as order_by %s and resets the page', async (sorting, orderBy) => {
            await mount()
            logic.actions.setPage(2)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSorting(sorting)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.page).toBe(1)
            expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
                ...DEFAULT_PARAMS,
                order_by: orderBy,
            })
        })

        it('falls back to the default order when the sort is cleared', async () => {
            await mount()
            logic.actions.setSorting({ columnKey: 'account_first_seen', order: 1 })
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSorting(null)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.sorting).toEqual({ columnKey: 'account_last_seen', order: -1 })
            expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', DEFAULT_PARAMS)
            expect(posthog.capture).toHaveBeenLastCalledWith(AccountsEvents.RelatedUsersSorted, {
                column: null,
                direction: 'cleared',
                read_source: ACCOUNT_PERSONS_READ_SOURCE,
            })
        })

        it('never sends a property name to analytics', async () => {
            await mount()
            logic.actions.addPropertyColumn('plan')

            logic.actions.setSorting({ columnKey: 'property:plan', order: 1 })

            expect(posthog.capture).toHaveBeenLastCalledWith(AccountsEvents.RelatedUsersSorted, {
                column: 'property',
                direction: 'asc',
                read_source: ACCOUNT_PERSONS_READ_SOURCE,
            })
        })

        it('ignores a saved sort on a property column that is not selected', async () => {
            await mount({ initialConfig: { sorting: { columnKey: 'property:plan', order: 1 } } })

            expect(mockList).toHaveBeenCalledWith(expect.any(String), 'acc-1', DEFAULT_PARAMS)
        })
    })

    describe('property columns', () => {
        it('adds a column to the selected keys after email and reloads the same page', async () => {
            await mount()
            logic.actions.setPage(2)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.addPropertyColumn('plan')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.page).toBe(2)
            expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
                ...DEFAULT_PARAMS,
                offset: ACCOUNT_PERSONS_PAGE_SIZE,
                select: '["email","plan"]',
            })
        })

        it('does not reload for duplicates, the email column, or columns past the limit', async () => {
            await mount()
            const keys = Array.from({ length: MAX_PERSON_PROPERTY_COLUMNS }, (_, index) => `prop_${index}`)
            keys.forEach((key) => logic.actions.addPropertyColumn(key))
            await expectLogic(logic).toFinishAllListeners()
            mockList.mockClear()

            logic.actions.addPropertyColumn('prop_0')
            logic.actions.addPropertyColumn('email')
            logic.actions.addPropertyColumn('one_too_many')
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).not.toHaveBeenCalled()
            expect(logic.values.propertyColumns).toEqual(keys)
        })

        it('returns to the default sort and first page when the sorted column is removed', async () => {
            await mount()
            logic.actions.addPropertyColumn('plan')
            logic.actions.setSorting({ columnKey: 'property:plan', order: -1 })
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.removePropertyColumn('plan')
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', DEFAULT_PARAMS)
        })

        it('keeps the sort when another column is removed', async () => {
            await mount()
            logic.actions.addPropertyColumn('plan')
            logic.actions.addPropertyColumn('role')
            logic.actions.setSorting({ columnKey: 'property:plan', order: -1 })
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.removePropertyColumn('role')
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
                ...DEFAULT_PARAMS,
                order_by: '-plan',
                select: '["email","plan"]',
            })
        })
    })

    describe('pagination', () => {
        it('requests the next page by offset and exposes has_more', async () => {
            mockList.mockResolvedValue(pageOf([person('a')], true))
            await mount()
            expect(logic.values.hasMore).toBe(true)

            logic.actions.setPage(2)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
                ...DEFAULT_PARAMS,
                offset: ACCOUNT_PERSONS_PAGE_SIZE,
            })
            expect(posthog.capture).toHaveBeenCalledWith(AccountsEvents.RelatedUsersPageChanged, {
                page: 2,
                read_source: ACCOUNT_PERSONS_READ_SOURCE,
            })
        })
    })

    describe('view state', () => {
        it('is loading until the first response arrives', async () => {
            const pending = deferred<AccountPersonsResponseApi>()
            mockList.mockReturnValue(pending.promise)
            logic = accountPersonsLogic({ accountId: 'acc-1' })
            logic.mount()

            expect(logic.values.viewState).toBe('loading')

            pending.resolve(pageOf([person('a')]))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.viewState).toBe('loaded')
        })

        it.each(['', 'Alice'])('shows not-ready rather than empty with search %s, then reloads', async (searchTerm) => {
            mockList.mockResolvedValue({ ...pageOf([]), membership_ready: false })
            await mount({ initialConfig: { searchTerm } })
            expect(logic.values.viewState).toBe('notReady')
            expect(logic.values.persons).toEqual([])
            expect(logic.values.hasMore).toBe(false)

            const retry = deferred<AccountPersonsResponseApi>()
            mockList.mockReturnValueOnce(retry.promise)
            logic.actions.loadPersons()
            expect(logic.values.viewState).toBe('loading')
            retry.resolve(pageOf([person('a')]))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.viewState).toBe('loaded')
        })

        it('is empty when an account has no people and nothing is filtered', async () => {
            mockList.mockResolvedValue(pageOf([]))
            await mount()

            expect(logic.values.viewState).toBe('empty')
        })

        it.each([
            ['search', (): void => logic.actions.setSearchTerm('nobody')],
            ['a property filter', (): void => logic.actions.setPropertyFilters([planFilter()])],
        ])('is filtered-empty when %s matches nobody', async (_, act) => {
            await mount()
            mockList.mockResolvedValue(pageOf([]))

            act()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.viewState).toBe('filteredEmpty')
        })

        it('is an error, not empty, when the request fails', async () => {
            mockList.mockRejectedValue(new Error('boom'))
            await mount()

            expect(logic.values.viewState).toBe('error')
            expect(logic.values.persons).toEqual([])
        })

        it('hides stale rows behind the error and shows loading while retrying', async () => {
            await mount()
            mockList.mockRejectedValueOnce(new Error('boom'))
            logic.actions.setPage(2)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.viewState).toBe('error')

            const retry = deferred<AccountPersonsResponseApi>()
            mockList.mockReturnValueOnce(retry.promise)
            logic.actions.loadPersons()
            expect(logic.values.viewState).toBe('loading')
            expect(logic.values.persons).toEqual([])

            retry.resolve(pageOf([person('b')]))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.viewState).toBe('loaded')
        })
    })

    describe('copying emails', () => {
        it('copies each address on its own line, once, and reports only the count', async () => {
            mockCopy.mockResolvedValue(true)
            await mount()

            logic.actions.copyEmails(['a@example.com', 'b@example.com', 'a@example.com'])
            await expectLogic(logic).toFinishAllListeners()

            expect(mockCopy).toHaveBeenCalledWith('a@example.com, b@example.com', 'email addresses')
            expect(posthog.capture).toHaveBeenCalledWith(AccountsEvents.RelatedUserEmailsCopied, {
                user_count: 2,
                read_source: ACCOUNT_PERSONS_READ_SOURCE,
            })
        })

        it('uses the singular noun for one address and reports nothing when the copy fails', async () => {
            mockCopy.mockResolvedValue(false)
            await mount()

            logic.actions.copyEmails(['a@example.com'])
            await expectLogic(logic).toFinishAllListeners()

            expect(mockCopy).toHaveBeenCalledWith('a@example.com', 'email address')
            expect(posthog.capture).not.toHaveBeenCalledWith(AccountsEvents.RelatedUserEmailsCopied, expect.anything())
        })
    })

    describe('saved tile config', () => {
        it('reports search, sort, columns, and filters so an account view can restore them', async () => {
            const onConfigChange = jest.fn()
            await mount({ onConfigChange })

            logic.actions.addPropertyColumn('plan')
            logic.actions.setSorting({ columnKey: 'property:plan', order: 1 })
            logic.actions.setPropertyFilters([planFilter()])
            await expectLogic(logic).toFinishAllListeners()

            expect(onConfigChange).toHaveBeenLastCalledWith({
                searchTerm: '',
                sorting: { columnKey: 'property:plan', order: 1 },
                propertyColumns: ['plan'],
                propertyFilters: [planFilter()],
            })
        })

        it('restores saved columns and filters into the first request', async () => {
            await mount({
                initialConfig: { propertyColumns: ['plan', 'email', 'plan'], propertyFilters: [planFilter()] },
            })

            expect(mockList).toHaveBeenCalledWith(expect.any(String), 'acc-1', {
                ...DEFAULT_PARAMS,
                select: '["email","plan"]',
                properties: JSON.stringify([planFilter()]),
            })
        })
    })
})
