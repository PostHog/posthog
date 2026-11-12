import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'

import { initKeaTests } from '~/test/init'

import {
    accountsNotebooksCreate,
    accountsNotebooksList,
    accountsNotebooksPartialUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountNotebookApi,
    PaginatedAccountNotebookListApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    accountNotebooksLogic,
    NOTES_PER_PAGE,
    sortingToViewOrdering,
    viewOrderingToSorting,
} from './accountNotebooksLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics (e.g. column config's
    // customPropertyDefinitionsList) call other generated functions on mount, and an
    // absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsNotebooksList: jest.fn(),
    accountsNotebooksCreate: jest.fn(),
    accountsNotebooksPartialUpdate: jest.fn(),
}))

const mockList = accountsNotebooksList as jest.MockedFunction<typeof accountsNotebooksList>
const mockCreate = accountsNotebooksCreate as jest.MockedFunction<typeof accountsNotebooksCreate>
const mockUpdate = accountsNotebooksPartialUpdate as jest.MockedFunction<typeof accountsNotebooksPartialUpdate>

const TEAM = String(MOCK_DEFAULT_TEAM.id)

const buildResponse = (
    results: AccountNotebookApi[] = [],
    count: number = results.length
): PaginatedAccountNotebookListApi => ({ results, count, next: null, previous: null })

const defaultListParams = {
    limit: NOTES_PER_PAGE,
    offset: 0,
    search: undefined,
    ordering: '-created_at',
    tags: undefined,
    created_by: undefined,
}

describe('accountNotebooksLogic', () => {
    let logic: ReturnType<typeof accountNotebooksLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockList.mockResolvedValue(buildResponse())
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mount = async (onConfigChange?: jest.Mock): Promise<void> => {
        logic = accountNotebooksLogic({ accountId: 'acc-1', onConfigChange })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('loads the first page with the default ordering', async () => {
        await mount()

        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', defaultListParams)
    })

    it('search resets to the first page and reloads with the search term', async () => {
        await mount()
        logic.actions.setPage(3)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearchTerm('renewal')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', { ...defaultListParams, search: 'renewal' })
    })

    it('sorting maps the column and direction onto the ordering param', async () => {
        await mount()

        logic.actions.setSorting({ columnKey: 'created_by', order: 1 })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockList).toHaveBeenLastCalledWith(
            TEAM,
            'acc-1',
            expect.objectContaining({ ordering: 'created_by', offset: 0 })
        )
    })

    it('tag filter is sent JSON-encoded and resets to the first page', async () => {
        await mount()
        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setTagsFilter(['risk', 'renewal'])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', {
            ...defaultListParams,
            tags: JSON.stringify(['risk', 'renewal']),
        })

        logic.actions.setTagsFilter([])
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', defaultListParams)
    })

    it('createNote opens the new note and reloads', async () => {
        await mount()
        mockCreate.mockResolvedValue({ short_id: 'note-1' } as AccountNotebookApi)
        mockList.mockResolvedValue(buildResponse([{ short_id: 'note-1' } as AccountNotebookApi], 1))

        logic.actions.createNote()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockCreate).toHaveBeenCalledTimes(1)
        expect(mockCreate).toHaveBeenCalledWith(TEAM, 'acc-1', expect.objectContaining({ content: expect.anything() }))
        expect(notebookPanelLogic.values.selectedNotebook).toBe('note-1')
        expect(logic.values.notebooks).toEqual([{ short_id: 'note-1' }])
    })

    it('createNote resets to the first page so the new note is visible', async () => {
        await mount()
        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()
        mockCreate.mockResolvedValue({ short_id: 'note-1' } as AccountNotebookApi)

        logic.actions.createNote()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', expect.objectContaining({ offset: 0 }))
    })

    it('updateNotebook patches the row in place without reloading the list', async () => {
        const note = { short_id: 'note-1', tags: [] } as unknown as AccountNotebookApi
        mockList.mockResolvedValue(buildResponse([note], 1))
        await mount()
        const listCalls = mockList.mock.calls.length
        mockUpdate.mockResolvedValue({ ...note, tags: ['risk'] })

        logic.actions.updateNotebook('note-1', { tags: ['risk'] })
        expect(logic.values.notebooks?.[0].tags).toEqual(['risk'])
        expect(logic.values.pendingNotebookTags['note-1']).toEqual(['risk'])
        await expectLogic(logic).toFinishAllListeners()

        expect(mockUpdate).toHaveBeenCalledWith(TEAM, 'acc-1', 'note-1', { tags: ['risk'] })
        expect(logic.values.notebooks).toEqual([{ ...note, tags: ['risk'] }])
        expect(logic.values.pendingNotebookTags).toEqual({})
        expect(mockList).toHaveBeenCalledTimes(listCalls)
    })

    it.each([false, true])(
        'keeps the latest optimistic tags while an older save finishes with failure=%s',
        async (fails) => {
            const note = { short_id: 'note-1', tags: [] } as unknown as AccountNotebookApi
            mockList.mockResolvedValue(buildResponse([note]))
            await mount()
            let resolveFirst!: (note: AccountNotebookApi) => void
            let rejectFirst!: (error: Error) => void
            let startFirst!: () => void
            const started = new Promise<void>((resolve) => {
                startFirst = resolve
            })
            const first = new Promise<AccountNotebookApi>((resolve, reject) => {
                resolveFirst = resolve
                rejectFirst = reject
            })
            mockUpdate.mockImplementationOnce(() => {
                startFirst()
                return first
            })
            let resolveLatest!: (note: AccountNotebookApi) => void
            let startLatest!: () => void
            const latestStarted = new Promise<void>((resolve) => {
                startLatest = resolve
            })
            const latest = new Promise<AccountNotebookApi>((resolve) => {
                resolveLatest = resolve
            })
            mockUpdate.mockImplementationOnce(() => {
                startLatest()
                return latest
            })
            logic.actions.updateNotebook(note.short_id, { tags: ['first'] })
            await started
            logic.actions.updateNotebook(note.short_id, { tags: ['first', 'risk'] })
            if (fails) {
                rejectFirst(new Error('Save failed'))
            } else {
                resolveFirst({ ...note, tags: ['first'] })
            }
            await latestStarted
            expect(logic.values.notebooks?.[0].tags).toEqual(['first', 'risk'])
            expect(logic.values.pendingNotebookTags[note.short_id]).toEqual(['first', 'risk'])
            resolveLatest({ ...note, tags: ['first', 'risk'] })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.notebooks?.[0].tags).toEqual(['first', 'risk'])
            expect(logic.values.pendingNotebookTags).toEqual({})
        }
    )

    it('exposes the live search, tags and sort as a view state', async () => {
        await mount()
        logic.actions.setSearchTerm('renewal')
        logic.actions.setTagsFilter(['risk'])
        logic.actions.setSorting({ columnKey: 'title', order: 1 })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.viewState).toEqual({
            filters: {
                search: 'renewal',
                tags: ['risk'],
                created_by: [],
                assigned_to: [],
                account_id: null,
                account_name: null,
            },
            ordering: 'title',
        })
    })

    it('author filter is sent as user ids, resets to the first page and is part of the view state', async () => {
        await mount()
        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setCreatedByFilter([7, 9])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', { ...defaultListParams, created_by: [7, 9] })
        expect(logic.values.viewState.filters.created_by).toEqual([7, 9])
    })

    it('resets to newest first, not the team tab default, when a view is cleared', async () => {
        await mount()

        expect(logic.values.defaultViewState.ordering).toBe('-created_at')
        logic.actions.setSorting({ columnKey: 'title', order: 1 })
        logic.actions.applyViewState(logic.values.defaultViewState)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sorting).toEqual({ columnKey: 'created_at', order: -1 })
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', defaultListParams)
    })

    it.each([null, 'acc-2'])(
        'persists and restores all view filters with account filter %s without account identity keys',
        async (accountId) => {
            const onConfigChange = jest.fn()
            await mount(onConfigChange)
            const callsBefore = mockList.mock.calls.length
            const viewState = {
                filters: {
                    search: 'renewal',
                    tags: ['risk'],
                    created_by: [7],
                    assigned_to: [9],
                    account_id: accountId,
                    account_name: accountId ? 'Example account' : null,
                },
                ordering: '-last_modified_at' as const,
            }

            logic.actions.applyViewState(viewState)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockList).toHaveBeenCalledTimes(callsBefore + 1)
            expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', {
                ...defaultListParams,
                search: 'renewal',
                tags: JSON.stringify(['risk']),
                created_by: [7],
                ordering: '-last_modified_at',
            })
            expect(logic.values.sorting).toEqual({ columnKey: 'last_modified_at', order: -1 })
            expect(onConfigChange).toHaveBeenLastCalledWith({
                searchTerm: 'renewal',
                sorting: { columnKey: 'last_modified_at', order: -1 },
                tagsFilter: ['risk'],
                createdByFilter: [7],
                currentViewId: null,
                passthroughViewFilters: {
                    assigned_to: [9],
                    accountFilter: { id: accountId, name: accountId ? 'Example account' : null },
                },
                passthroughViewOrdering: null,
            })
            expect(logic.values.viewState).toEqual(viewState)

            const initialConfig = onConfigChange.mock.lastCall?.[0]
            expect(initialConfig.passthroughViewFilters).not.toHaveProperty('account_id')
            logic.unmount()
            logic = accountNotebooksLogic({ accountId: 'acc-1', initialConfig })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.viewState).toEqual(viewState)
        }
    )

    it('applying a view ordered by a column this list cannot sort falls back to the default sort', async () => {
        await mount()

        logic.actions.applyViewState({
            filters: { search: '', tags: [], created_by: [], assigned_to: [], account_id: null, account_name: null },
            ordering: 'account_name',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sorting).toEqual({ columnKey: 'created_at', order: -1 })
        expect(logic.values.viewState.ordering).toBe('account_name')
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', defaultListParams)
        logic.actions.setSorting({ columnKey: 'title', order: 1 })
        expect(logic.values.viewState.ordering).toBe('title')
    })
})

describe('view ordering mapping', () => {
    it.each([
        [null, '-created_at'],
        [{ columnKey: 'created_at', order: 1 }, 'created_at'],
        [{ columnKey: 'title', order: -1 }, '-title'],
        [{ columnKey: 'created_by', order: -1 }, '-created_by'],
        [{ columnKey: 'tags', order: 1 }, '-created_at'],
    ])('maps sorting %j to view ordering %s', (sorting, expected) => {
        expect(sortingToViewOrdering(sorting as { columnKey: string; order: 1 | -1 } | null)).toBe(expected)
    })

    it.each([
        ['-last_modified_at', { columnKey: 'last_modified_at', order: -1 }],
        ['title', { columnKey: 'title', order: 1 }],
        ['account_name', { columnKey: 'created_at', order: -1 }],
    ] as const)('maps view ordering %s to sorting %j', (ordering, expected) => {
        expect(viewOrderingToSorting(ordering)).toEqual(expected)
    })
})
