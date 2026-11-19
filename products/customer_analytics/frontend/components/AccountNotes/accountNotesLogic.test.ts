import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import {
    accountNotesList,
    accountsList,
    accountsNotebooksPartialUpdate,
} from 'products/customer_analytics/frontend/generated/api'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { accountNotesLogic } from './accountNotesLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountNotesList: jest.fn(),
    accountsList: jest.fn(),
    accountsNotebooksPartialUpdate: jest.fn(),
}))

const mockAccountNotesList = accountNotesList as jest.MockedFunction<typeof accountNotesList>
const mockAccountsList = accountsList as jest.MockedFunction<typeof accountsList>
const mockPartialUpdate = accountsNotebooksPartialUpdate as jest.MockedFunction<typeof accountsNotebooksPartialUpdate>

const CURRENT_USER_ID = 42

describe('accountNotesLogic', () => {
    let logic: ReturnType<typeof accountNotesLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        mockAccountNotesList.mockResolvedValue({ count: 0, results: [] } as any)
        mockAccountsList.mockResolvedValue({ count: 0, results: [] } as any)
        // mineOnly is persisted to localStorage on the shared scene logic; isolate tests.
        localStorage.clear()
        userLogic.actions.loadUserSuccess({ id: CURRENT_USER_ID } as unknown as UserType)
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
    })

    // "My accounts" (assigned-to-me) is shared with the Accounts tab via the scene logic's
    // mineOnly toggle; "My notes" (created-by-me) is notes-only and must stay independent.
    it('"My accounts" resolves to the current user, sends assigned_to, and syncs the shared toggle', async () => {
        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setAssignedToCurrentUser(true)
        }).toFinishAllListeners()

        expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
        expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(true)
        expect(mockAccountNotesList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ assigned_to: [CURRENT_USER_ID] })
        )
    })

    it('"My notes" does not touch the shared "My accounts" toggle', async () => {
        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setCreatedByCurrentUser(true)
        }).toFinishAllListeners()

        expect(logic.values.createdByCurrentUser).toBe(true)
        expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(false)
    })

    it('restores "My accounts" from the shared toggle on mount', async () => {
        customerAnalyticsSceneLogic.mount()
        customerAnalyticsSceneLogic.actions.setMineOnly(true)

        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.assignedToCurrentUser).toBe(true)
        expect(mockAccountNotesList).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ assigned_to: [CURRENT_USER_ID] })
        )
    })

    // Regression: a fresh page load can mount this logic before userLogic resolves the user,
    // so afterMount can't apply the persisted choice (currentUserId null). The user resolving
    // later must still apply it — otherwise the returning user sees all notes until they toggle.
    it('applies a persisted "My accounts" choice when the user resolves after mount', async () => {
        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // Persisted choice present but not yet applied (user was unknown during restore).
        customerAnalyticsSceneLogic.actions.setMineOnly(true)
        expect(logic.values.assignedToCurrentUser).toBe(false)

        await expectLogic(logic, () => {
            userLogic.actions.loadUserSuccess({ id: CURRENT_USER_ID } as unknown as UserType)
        }).toFinishAllListeners()

        expect(logic.values.assignedToFilter).toEqual([CURRENT_USER_ID])
        expect(mockAccountNotesList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ assigned_to: [CURRENT_USER_ID] })
        )
    })

    it('loads with the default ordering and without a tag param', async () => {
        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccountNotesList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ ordering: '-last_modified_at', tags: undefined })
        )
    })

    it('tag filter is sent JSON-encoded and resets the page', async () => {
        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setPage(3)
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setTagsFilter(['risk'])
        }).toFinishAllListeners()

        expect(logic.values.page).toBe(1)
        expect(mockAccountNotesList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ tags: JSON.stringify(['risk']), offset: 0 })
        )
    })

    it('ordering maps to the table sorting and is sent to the API', async () => {
        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setOrdering('title')
        }).toFinishAllListeners()

        expect(logic.values.sorting).toEqual({ columnKey: 'title', order: 1 })
        expect(mockAccountNotesList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ ordering: 'title', offset: 0 })
        )
    })

    it('applyViewState replaces every filter at once and syncs the shared toggle', async () => {
        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const callsBefore = mockAccountNotesList.mock.calls.length

        await expectLogic(logic, () => {
            logic.actions.applyViewState({
                filters: {
                    search: 'renewal',
                    tags: ['risk'],
                    created_by: [7],
                    assigned_to: [CURRENT_USER_ID],
                    account_id: 'acc-1',
                    account_name: 'Example account',
                },
                ordering: '-created_at',
            })
        }).toFinishAllListeners()

        expect(mockAccountNotesList).toHaveBeenCalledTimes(callsBefore + 1)
        expect(mockAccountNotesList).toHaveBeenLastCalledWith(expect.any(String), {
            search: 'renewal',
            account_id: 'acc-1',
            created_by: [7],
            assigned_to: [CURRENT_USER_ID],
            tags: JSON.stringify(['risk']),
            ordering: '-created_at',
            limit: 50,
            offset: 0,
        })
        expect(logic.values.accountFilter).toEqual({ id: 'acc-1', name: 'Example account' })
        expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(true)
    })

    it('sorts by author', async () => {
        logic = accountNotesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setOrdering('-created_by')
        }).toFinishAllListeners()

        expect(logic.values.sorting).toEqual({ columnKey: 'created_by', order: -1 })
        expect(mockAccountNotesList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ ordering: '-created_by' })
        )
    })

    it.each([false, true])(
        'edits note tags optimistically and rolls back on failure=%s without reloading',
        async (fails) => {
            const note = { short_id: 'note-1', account_id: 'acc-9', tags: [] } as any
            mockAccountNotesList.mockResolvedValue({ count: 1, results: [note] } as any)
            if (fails) {
                mockPartialUpdate.mockRejectedValue(new Error('Save failed'))
            } else {
                mockPartialUpdate.mockResolvedValue({ short_id: 'note-1', tags: ['risk'] } as any)
            }
            logic = accountNotesLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockAccountNotesList.mock.calls.length

            logic.actions.updateNoteTags(note, ['risk'])
            expect(logic.values.accountNotes[0].tags).toEqual(['risk'])
            expect(logic.values.pendingNoteTags['note-1']).toEqual(['risk'])
            await expectLogic(logic).toFinishAllListeners()

            expect(mockPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'acc-9', 'note-1', { tags: ['risk'] })
            expect(logic.values.accountNotes[0].tags).toEqual(fails ? [] : ['risk'])
            expect(logic.values.pendingNoteTags).toEqual({})
            expect(mockAccountNotesList).toHaveBeenCalledTimes(callsBefore)
        }
    )

    it('clearing a view goes back to no filters and last modified first', () => {
        logic = accountNotesLogic()
        logic.mount()

        expect(logic.values.defaultViewState.ordering).toBe('-last_modified_at')
        expect(logic.values.defaultViewState.filters.tags).toEqual([])
    })
})
