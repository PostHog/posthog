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
        expect(logic.values.updatingShortId).toBe('note-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(mockUpdate).toHaveBeenCalledWith(TEAM, 'acc-1', 'note-1', { tags: ['risk'] })
        expect(logic.values.notebooks).toEqual([{ ...note, tags: ['risk'] }])
        expect(logic.values.updatingShortId).toBeNull()
        expect(mockList).toHaveBeenCalledTimes(listCalls)
    })

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

    it('applyViewState replaces search, tags and sort at once, loads once and echoes the rest back', async () => {
        const onConfigChange = jest.fn()
        await mount(onConfigChange)
        const callsBefore = mockList.mock.calls.length
        const viewState = {
            filters: {
                search: 'renewal',
                tags: ['risk'],
                created_by: [7],
                assigned_to: [9],
                account_id: 'acc-2',
                account_name: 'Example account',
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
            ordering: '-last_modified_at',
        })
        expect(logic.values.sorting).toEqual({ columnKey: 'last_modified_at', order: -1 })
        expect(onConfigChange).toHaveBeenLastCalledWith({
            searchTerm: 'renewal',
            sorting: { columnKey: 'last_modified_at', order: -1 },
        })
        expect(logic.values.viewState).toEqual(viewState)
    })

    it('applying a view ordered by a column this list cannot sort falls back to the default sort', async () => {
        await mount()

        logic.actions.applyViewState({
            filters: { search: '', tags: [], created_by: [], assigned_to: [], account_id: null, account_name: null },
            ordering: 'account_name',
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sorting).toEqual({ columnKey: 'created_at', order: -1 })
        expect(mockList).toHaveBeenLastCalledWith(TEAM, 'acc-1', defaultListParams)
    })
})

describe('view ordering mapping', () => {
    it.each([
        [null, '-created_at'],
        [{ columnKey: 'created_at', order: 1 }, 'created_at'],
        [{ columnKey: 'title', order: -1 }, '-title'],
        [{ columnKey: 'created_by', order: -1 }, '-created_at'],
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
