import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { accountNotesList, accountsList } from 'products/customer_analytics/frontend/generated/api'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { accountNotesLogic } from './accountNotesLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountNotesList: jest.fn(),
    accountsList: jest.fn(),
}))

const mockAccountNotesList = accountNotesList as jest.MockedFunction<typeof accountNotesList>
const mockAccountsList = accountsList as jest.MockedFunction<typeof accountsList>

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
})
