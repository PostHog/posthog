import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import {
    accountsList,
    accountsRetrieve,
    customerTasksCreate,
    customerTasksList,
    customerTasksRetrieve,
    customerTasksPartialUpdate,
} from 'products/customer_analytics/frontend/generated/api'
import type { CustomerTaskApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerTasksPersistencePrefix, parseCustomerTaskSearchParams } from './customerTaskFilters'
import { customerTasksLogic } from './customerTasksLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountsList: jest.fn(),
    accountsRetrieve: jest.fn(),
    customerTasksArchiveCreate: jest.fn(),
    customerTasksCreate: jest.fn(),
    customerTasksList: jest.fn(),
    customerTasksRetrieve: jest.fn(),
    customerTasksPartialUpdate: jest.fn(),
    customerTasksRestoreCreate: jest.fn(),
}))

const mockCreate = customerTasksCreate as jest.MockedFunction<typeof customerTasksCreate>
const mockList = customerTasksList as jest.MockedFunction<typeof customerTasksList>
const mockAccounts = accountsList as jest.MockedFunction<typeof accountsList>
const mockUpdate = customerTasksPartialUpdate as jest.MockedFunction<typeof customerTasksPartialUpdate>
const mockAccount = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>

const URL_ACCOUNT_ID = '0199ed4a-5c03-0000-3220-df21df612e95'
const SECOND_URL_ACCOUNT_ID = '0199ed4a-5c03-0000-3220-df21df612e96'

function task(canEdit = true): CustomerTaskApi {
    return {
        id: 'task-1',
        account: null,
        name: 'Follow up',
        description: null,
        status: 'open',
        assigned_to: null,
        due_at: null,
        completed_at: null,
        completed_by: null,
        created_by: null,
        archived_at: null,
        created_at: '2026-09-02T10:00:00Z',
        updated_at: '2026-09-02T10:00:00Z',
        can_edit: canEdit,
        can_restore: false,
    }
}

describe('customerTasksLogic', () => {
    let logic: ReturnType<typeof customerTasksLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        mockCreate.mockResolvedValue(task())
        mockList.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockAccounts.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
        mockUpdate.mockResolvedValue(task())
        mockAccount.mockResolvedValue({ id: URL_ACCOUNT_ID, name: 'Acme' } as never)
        router.actions.push(urls.customerAnalyticsTasks())
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
    })

    test.each([
        ['account', 'account-1', 20, { account_id: 'account-1' }],
        ['inbox', undefined, 50, { assigned_to: 'me' }],
    ])('loads %s with its page size and default filters', async (context, accountId, pageSize, filter) => {
        logic = customerTasksLogic({ context: context as 'account' | 'inbox', accountId })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                ...filter,
                statuses: 'open,in_progress',
                archive_state: 'active',
                ordering: 'due_at',
                limit: pageSize,
                offset: 0,
            })
        )
    })

    test('opens a linked task even when persisted filters exclude it', async () => {
        const linkedTask = task()
        ;(customerTasksRetrieve as jest.Mock).mockResolvedValue(linkedTask)
        router.actions.push(urls.customerAnalyticsTasks(), { task_id: linkedTask.id })
        logic = customerTasksLogic({ context: 'inbox' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.modalTask).toEqual(linkedTask)
        expect(logic.values.modalOpen).toBe(true)
    })

    test('creates a task for the current account without exposing a different account', async () => {
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openCreateModal()
        logic.actions.setDraftName('Follow up')
        logic.actions.submitModal()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockCreate).toHaveBeenCalledWith(expect.any(String), {
            account_id: 'account-1',
            name: 'Follow up',
            description: null,
            assigned_to_id: null,
            due_at: null,
        })
    })

    test('keeps the create form and its drafts when the create fails', async () => {
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as never)
        mockCreate.mockRejectedValueOnce(
            new ApiError(undefined, 400, undefined, { assigned_to_id: 'Select a member of this project.' })
        )
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openCreateModal()
        logic.actions.setDraftName('Follow up')
        logic.actions.setDraftDescription('Ask about the renewal')
        logic.actions.submitModal()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.modalOpen).toBe(true)
        expect(logic.values.draftName).toBe('Follow up')
        expect(logic.values.draftDescription).toBe('Ask about the renewal')
        expect(toast).toHaveBeenCalledWith('Select a member of this project.')
        toast.mockRestore()
    })

    test.each([
        ['assigns', null, 'account-1'],
        ['removes', { id: 'account-1', name: 'Acme' }, null],
    ])('%s an account while editing a task', async (_, account, selectedAccountId) => {
        const originalTask = { ...task(), account }
        mockList.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [originalTask] })
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openEditModal(originalTask)
        expect(logic.values.draftAccount).toEqual(account)
        logic.actions.setDraftAccount(selectedAccountId ? { id: selectedAccountId, name: 'Acme' } : null)
        logic.actions.submitModal()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockUpdate).toHaveBeenCalledWith(expect.any(String), originalTask.id, {
            account_id: selectedAccountId,
        })
    })

    test('assigns an inbox draft to the current user under the default filter', async () => {
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true })
        logic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openCreateModal()

        expect(logic.values.draftAssignedTo).toMatchObject({
            id: MOCK_DEFAULT_USER.id,
            email: MOCK_DEFAULT_USER.email,
        })
        logic.actions.setDraftAssignedTo(null)
        expect(logic.values.draftAssignedTo).toBeNull()
    })

    test('persists inbox filters for one team and user, then resets them to defaults', async () => {
        const prefix = customerTasksPersistencePrefix(1, 42)
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setFilters({ status: 'completed', assignee: 'unassigned' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters).toMatchObject({ status: 'completed', assignee: 'unassigned' })
        logic.unmount()
        router.actions.push(urls.customerAnalyticsTasks())

        const otherUserLogic = customerTasksLogic({
            context: 'inbox',
            canViewAll: true,
            persistPrefix: customerTasksPersistencePrefix(1, 7),
        })
        otherUserLogic.mount()
        await expectLogic(otherUserLogic).toFinishAllListeners()
        expect(otherUserLogic.values.filters).toMatchObject({ status: 'open', assignee: 'me' })
        otherUserLogic.unmount()

        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        expect(logic.values.filters).toMatchObject({ status: 'completed', assignee: 'unassigned' })
        logic.actions.resetFilters()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters).toMatchObject({ status: 'open', assignee: 'me' })
        expect(JSON.stringify(localStorage)).not.toContain('completed')
    })

    test('reloads the server-sorted page after setting a due date', async () => {
        const originalTask = task()
        const updatedTask = { ...originalTask, due_at: '2026-09-03T12:00:00Z' }
        const otherTask = { ...task(), id: 'task-2', name: 'Other task' }
        mockList.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [originalTask] })
        mockUpdate.mockResolvedValueOnce(updatedTask)
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockClear()
        mockList.mockResolvedValueOnce({ count: 2, next: null, previous: null, results: [updatedTask, otherTask] })

        logic.actions.updateTask(originalTask.id, { due_at: updatedTask.due_at })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockList).toHaveBeenCalledTimes(1)
        expect(logic.values.tasks).toEqual([updatedTask, otherTask])
    })

    test.each([
        ['the field the server rejected', { assigned_to_id: 'Select a member of this project.' }, 400],
        ['the detail the server sent', { detail: 'Restore this task before editing it.' }, 409],
    ])('reports %s instead of asking for a retry', async (_name, body, status) => {
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as never)
        mockList.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [task()] })
        mockUpdate.mockRejectedValueOnce(new ApiError(undefined, status, undefined, body))
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.updateTask('task-1', { assigned_to_id: 9 })
        await expectLogic(logic).toFinishAllListeners()

        expect(toast).toHaveBeenCalledWith(Object.values(body)[0])
        toast.mockRestore()
    })

    test('does not submit an unchanged modal, an uneditable task, or an archived task', async () => {
        const accountTask = { ...task(), account: { id: 'account-1', name: 'Acme' } }
        mockList.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [accountTask] })
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openEditModal(logic.values.tasks[0])
        logic.actions.submitModal()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockUpdate).not.toHaveBeenCalled()
        expect(logic.values.modalOpen).toBe(false)

        mockList.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [task(false)] })
        logic.actions.loadTaskPage()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.updateTask('task-1', { name: 'Changed' })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockUpdate).not.toHaveBeenCalled()

        const archivedTask = { ...task(), archived_at: '2026-09-02T11:00:00Z' }
        mockList.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [archivedTask] })
        logic.actions.loadTaskPage()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.updateTask('task-1', { name: 'Changed' })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockUpdate).not.toHaveBeenCalled()
    })
    test('lets a link override the filters the person left behind', async () => {
        const prefix = customerTasksPersistencePrefix(1, 42)
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        logic.actions.setFilters({ status: 'completed', assignee: 'unassigned' })
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()

        router.actions.push(urls.customerAnalyticsTasks(), { due: 'overdue', assignee: 'me' })
        mockList.mockClear()
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filters).toMatchObject({ status: 'open', assignee: 'me', due: 'overdue' })
        expect(mockList).toHaveBeenCalledTimes(1)
        expect(mockList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ assigned_to: 'me', statuses: 'open,in_progress', due_before: expect.any(String) })
        )
    })

    test('keeps the persisted filters when the link carries none', async () => {
        const prefix = customerTasksPersistencePrefix(1, 42)
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        logic.actions.setFilters({ status: 'completed' })
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()

        router.actions.push(urls.customerAnalyticsTasks())
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filters).toMatchObject({ status: 'completed' })
    })

    test('keeps the persisted filters when a link only sorts', async () => {
        const prefix = customerTasksPersistencePrefix(1, 42)
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        logic.actions.setFilters({ status: 'completed' })
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()

        router.actions.push(urls.customerAnalyticsTasks(), { sort: '-name' })
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true, persistPrefix: prefix })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filters).toMatchObject({ status: 'completed' })
        expect(logic.values.ordering).toBe('-name')
    })

    test('keeps a digits-only search the router reads back as a number', async () => {
        router.actions.push(`${urls.customerAnalyticsTasks()}?search=123`)
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams.search).toBe(123)
        expect(logic.values.filters.search).toBe('123')
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ search: '123' }))

        logic.actions.setSearch('456')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filters.search).toBe('456')
    })

    test('writes the inbox filters, sort and page back to the link', async () => {
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setFilters({ due: 'overdue', status: 'all' })
        logic.actions.setTaskOrdering('-updated_at')
        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toMatchObject({
            due: 'overdue',
            status: 'all',
            sort: '-updated_at',
            page: 2,
        })
        expect(parseCustomerTaskSearchParams(router.values.searchParams)).toEqual({
            filters: logic.values.filters,
            ordering: logic.values.ordering,
            page: logic.values.page,
        })
    })

    test('names the account a link can only identify by id', async () => {
        router.actions.push(urls.customerAnalyticsTasks(), { account: URL_ACCOUNT_ID })
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockAccount).toHaveBeenCalledWith(expect.any(String), URL_ACCOUNT_ID)
        expect(logic.values.filters.account).toEqual({ id: URL_ACCOUNT_ID, name: 'Acme' })
        expect(mockList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ account_id: URL_ACCOUNT_ID })
        )
    })

    test('ignores a slow account read for an account the person moved off', async () => {
        let resolveAccount = (): void => {}
        mockAccount.mockReturnValueOnce(
            new Promise((resolve) => {
                resolveAccount = () => resolve({ id: URL_ACCOUNT_ID, name: 'Acme' } as never)
            })
        )
        router.actions.push(urls.customerAnalyticsTasks(), { account: URL_ACCOUNT_ID })
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true })
        logic.mount()

        logic.actions.setAccountFilter({ id: SECOND_URL_ACCOUNT_ID, name: 'Initech' })
        resolveAccount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filters.account).toEqual({ id: SECOND_URL_ACCOUNT_ID, name: 'Initech' })
    })

    test('reports where an inbox visit came from once, then drops the source', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        router.actions.push(urls.customerAnalyticsTasks(), { source: 'task_digest', due: 'overdue' })
        logic = customerTasksLogic({ context: 'inbox', canViewAll: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(captureSpy).toHaveBeenCalledWith('customer analytics tasks inbox viewed', { source: 'task_digest' })
        expect(router.values.searchParams).not.toHaveProperty('source')
        expect(logic.values.filters.due).toBe('overdue')
        captureSpy.mockRestore()
    })

    test('leaves the link alone for the account tab', async () => {
        router.actions.push(urls.customerAnalyticsTasks())
        logic = customerTasksLogic({ context: 'account', accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setFilters({ status: 'completed' })
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({})
    })
})
