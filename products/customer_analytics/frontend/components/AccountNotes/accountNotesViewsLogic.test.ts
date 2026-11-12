import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    accountNotesList,
    accountsList,
    accountsNotebooksList,
} from 'products/customer_analytics/frontend/generated/api'
import {
    columnConfigurationsCreate,
    columnConfigurationsDestroy,
    columnConfigurationsList,
    columnConfigurationsPartialUpdate,
} from 'products/product_analytics/frontend/generated/api'
import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { accountNotebooksLogic } from '../Accounts/accountNotebooksLogic'
import { accountNotesLogic } from './accountNotesLogic'
import {
    ACCOUNT_NOTES_VIEWS_CONTEXT_KEY,
    ACCOUNT_NOTES_VIEW_COLUMNS,
    accountNotesViewsLogic,
    describeAccountNotesView,
    deserializeAccountNotesView,
    serializeAccountNotesView,
} from './accountNotesViewsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    accountNotesList: jest.fn(),
    accountsList: jest.fn(),
    accountsNotebooksList: jest.fn(),
    accountsNotebooksCreate: jest.fn(),
    accountsNotebooksPartialUpdate: jest.fn(),
}))

jest.mock('products/product_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/product_analytics/frontend/generated/api'),
    columnConfigurationsCreate: jest.fn(),
    columnConfigurationsDestroy: jest.fn(),
    columnConfigurationsList: jest.fn(),
    columnConfigurationsPartialUpdate: jest.fn(),
}))

const mockNotesList = jest.mocked(accountNotesList)
const mockAccountsList = jest.mocked(accountsList)
const mockNotebooksList = jest.mocked(accountsNotebooksList)
const mockList = jest.mocked(columnConfigurationsList)
const mockCreate = jest.mocked(columnConfigurationsCreate)
const mockDelete = jest.mocked(columnConfigurationsDestroy)
const mockUpdate = jest.mocked(columnConfigurationsPartialUpdate)

const buildView = (overrides: Partial<ColumnConfigurationApi> = {}): ColumnConfigurationApi => ({
    id: 'view-1',
    context_key: ACCOUNT_NOTES_VIEWS_CONTEXT_KEY,
    columns: [],
    name: 'Renewal risks',
    filters: { search: 'renewal', tags: ['risk'], created_by: [], assigned_to: [] },
    order_by: ['title'],
    properties: {},
    visibility: 'shared',
    created_by: MOCK_DEFAULT_USER.id,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
})

const response = (views: ColumnConfigurationApi[]): Awaited<ReturnType<typeof columnConfigurationsList>> => ({
    count: views.length,
    results: views,
    next: null,
    previous: null,
})

describe('accountNotesViewsLogic', () => {
    let logic: ReturnType<typeof accountNotesViewsLogic.build>

    const settle = async (): Promise<void> => {
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(accountNotesLogic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        mockNotesList.mockReset().mockResolvedValue({ count: 0, results: [] } as any)
        mockAccountsList.mockReset().mockResolvedValue({ count: 0, results: [] } as any)
        mockNotebooksList.mockReset().mockResolvedValue({ count: 0, results: [] } as any)
        mockList.mockReset().mockResolvedValue(response([buildView()]))
        mockCreate.mockReset()
        mockDelete.mockReset().mockResolvedValue(undefined)
        mockUpdate.mockReset()
        logic = accountNotesViewsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
    })

    it('loads the views for the notes context key', async () => {
        await settle()

        expect(mockList).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ context_key: ACCOUNT_NOTES_VIEWS_CONTEXT_KEY })
        )
        expect(logic.values.views).toHaveLength(1)
        expect(logic.values.currentViewId).toBeNull()
        expect(logic.values.isDirty).toBe(false)
    })

    it('selecting a view applies its filters and ordering, and edits make it dirty', async () => {
        await settle()

        logic.actions.selectView('view-1')
        await settle()

        expect(logic.values.currentView?.name).toBe('Renewal risks')
        expect(accountNotesLogic.values.search).toBe('renewal')
        expect(accountNotesLogic.values.tagsFilter).toEqual(['risk'])
        expect(accountNotesLogic.values.ordering).toBe('title')
        expect(mockNotesList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({
                search: 'renewal',
                tags: JSON.stringify(['risk']),
                ordering: 'title',
            })
        )
        expect(logic.values.isDirty).toBe(false)

        accountNotesLogic.actions.setTagsFilter(['risk', 'churn'])
        await settle()
        expect(logic.values.isDirty).toBe(true)

        logic.actions.clearView()
        await settle()
        expect(logic.values.currentViewId).toBeNull()
        expect(accountNotesLogic.values.search).toBe('')
        expect(accountNotesLogic.values.tagsFilter).toEqual([])
        expect(accountNotesLogic.values.ordering).toBe('-last_modified_at')
    })

    it('saves the live filters as a new view and selects it', async () => {
        await settle()
        accountNotesLogic.actions.setSearch('  onboarding ')
        accountNotesLogic.actions.setTagsFilter(['onboarding'])
        await settle()
        const created = buildView({
            id: 'view-2',
            name: 'Onboarding',
            visibility: 'private',
            filters: {
                search: 'onboarding',
                tags: ['onboarding'],
                created_by: [],
                assigned_to: [],
                account_id: null,
                account_name: null,
            },
            order_by: ['-last_modified_at'],
        })
        mockCreate.mockResolvedValue(created)

        logic.actions.setViewFormValues({ name: '  Onboarding  ', visibility: 'private' })
        await expectLogic(logic, () => logic.actions.submitViewForm()).toDispatchActions(['submitViewFormSuccess'])

        expect(mockCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            context_key: ACCOUNT_NOTES_VIEWS_CONTEXT_KEY,
            name: 'Onboarding',
            visibility: 'private',
            columns: ACCOUNT_NOTES_VIEW_COLUMNS,
            order_by: ['-last_modified_at'],
            filters: {
                search: 'onboarding',
                tags: ['onboarding'],
                created_by: [],
                assigned_to: [],
                account_id: null,
                account_name: null,
            },
        })
        expect(logic.values.currentViewId).toBe('view-2')
        expect(logic.values.views.map((view) => view.id)).toEqual(['view-1', 'view-2'])
        expect(logic.values.isDirty).toBe(false)
    })

    it('updates the selected view with the live filters and deletes it', async () => {
        await settle()
        logic.actions.selectView('view-1')
        await settle()
        accountNotesLogic.actions.setOrdering('-created_at')
        await settle()
        mockUpdate.mockResolvedValue(buildView({ order_by: ['-created_at'] }))

        await expectLogic(logic, () => logic.actions.updateView({ id: 'view-1', updates: {} })).toDispatchActions([
            'updateViewSuccess',
        ])
        expect(mockUpdate).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            'view-1',
            expect.objectContaining({ order_by: ['-created_at'] })
        )
        expect(logic.values.isDirty).toBe(false)

        await expectLogic(logic, () => logic.actions.deleteView({ id: 'view-1' })).toDispatchActions([
            'deleteViewSuccess',
        ])
        expect(mockDelete).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'view-1')
        expect(logic.values.views).toEqual([])
        expect(logic.values.currentViewId).toBeNull()
        expect(accountNotesLogic.values.viewState).toEqual(accountNotesLogic.values.defaultViewState)
    })

    describe('keyed to an account notes tile', () => {
        let tileLogic: ReturnType<typeof accountNotebooksLogic.build>
        let tileViewsLogic: ReturnType<typeof accountNotesViewsLogic.build>

        beforeEach(() => {
            tileLogic = accountNotebooksLogic({ accountId: 'acc-1' })
            tileLogic.mount()
            tileViewsLogic = accountNotesViewsLogic({ sourceKey: tileLogic.pathString, sourceLogic: tileLogic })
            tileViewsLogic.mount()
        })

        afterEach(() => {
            tileViewsLogic.unmount()
            tileLogic.unmount()
        })

        it('lists the same views and applies one to the tile, leaving the Notes tab alone', async () => {
            await expectLogic(tileViewsLogic).toFinishAllListeners()
            await expectLogic(tileLogic).toFinishAllListeners()
            expect(tileViewsLogic).not.toBe(logic)
            expect(tileViewsLogic.values.views.map((view) => view.id)).toEqual(['view-1'])

            tileViewsLogic.actions.selectView('view-1')
            await expectLogic(tileViewsLogic).toFinishAllListeners()
            await expectLogic(tileLogic).toFinishAllListeners()

            expect(tileLogic.values.searchTerm).toBe('renewal')
            expect(tileLogic.values.tagsFilter).toEqual(['risk'])
            expect(tileLogic.values.sorting).toEqual({ columnKey: 'title', order: 1 })
            expect(mockNotebooksList).toHaveBeenLastCalledWith(
                expect.any(String),
                'acc-1',
                expect.objectContaining({ search: 'renewal', tags: JSON.stringify(['risk']), ordering: 'title' })
            )
            expect(tileViewsLogic.values.isDirty).toBe(false)
            expect(accountNotesLogic.values.search).toBe('')
            expect(logic.values.currentViewId).toBeNull()

            tileLogic.actions.setTagsFilter([])
            await expectLogic(tileLogic).toFinishAllListeners()
            expect(tileViewsLogic.values.isDirty).toBe(true)

            tileViewsLogic.unmount()
            tileViewsLogic = accountNotesViewsLogic({ sourceKey: tileLogic.pathString, sourceLogic: tileLogic })
            tileViewsLogic.mount()
            await expectLogic(tileViewsLogic).toFinishAllListeners()
            expect(tileViewsLogic.values.currentViewId).toBe('view-1')
            expect(tileViewsLogic.values.isDirty).toBe(true)
        })

        it.each(['account_name', '-account_name'])(
            'preserves team-only ordering %s when an account applies and updates a view',
            async (ordering) => {
                const view = buildView({ order_by: [ordering] })
                tileViewsLogic.actions.loadViewsSuccess([view])
                tileViewsLogic.actions.selectView(view.id)
                await expectLogic(tileLogic).toFinishAllListeners()
                expect(tileLogic.values.sorting).toEqual({ columnKey: 'created_at', order: -1 })
                expect(tileViewsLogic.values.isDirty).toBe(false)
                tileLogic.actions.setTagsFilter(['call'])
                mockUpdate.mockResolvedValue(
                    buildView({
                        order_by: [ordering],
                        filters: { ...deserializeAccountNotesView(view).filters, tags: ['call'] },
                    })
                )
                await expectLogic(tileViewsLogic, () =>
                    tileViewsLogic.actions.updateView({ id: view.id, updates: {} })
                ).toDispatchActions(['updateViewSuccess'])
                expect(mockUpdate).toHaveBeenLastCalledWith(
                    String(MOCK_DEFAULT_TEAM.id),
                    view.id,
                    expect.objectContaining({ order_by: [ordering] })
                )
                expect(tileViewsLogic.values.isDirty).toBe(false)
            }
        )

        it('saves a new view from the tile filters', async () => {
            await expectLogic(tileViewsLogic).toFinishAllListeners()
            tileLogic.actions.setTagsFilter(['calls'])
            await expectLogic(tileLogic).toFinishAllListeners()
            mockCreate.mockResolvedValue(buildView({ id: 'view-3', name: 'Calls' }))

            tileViewsLogic.actions.setViewFormValues({ name: 'Calls', visibility: 'shared' })
            await expectLogic(tileViewsLogic, () => tileViewsLogic.actions.submitViewForm()).toDispatchActions([
                'submitViewFormSuccess',
            ])

            expect(mockCreate).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
                context_key: ACCOUNT_NOTES_VIEWS_CONTEXT_KEY,
                name: 'Calls',
                visibility: 'shared',
                columns: ACCOUNT_NOTES_VIEW_COLUMNS,
                order_by: ['-created_at'],
                filters: {
                    search: '',
                    tags: ['calls'],
                    created_by: [],
                    assigned_to: [],
                    account_id: null,
                    account_name: null,
                },
            })
            expect(tileViewsLogic.values.currentViewId).toBe('view-3')
            const restored = accountNotebooksLogic({ accountId: 'acc-2', initialConfig: tileLogic.values.tileConfig })
            restored.mount()
            try {
                await expectLogic(restored).toFinishAllListeners()
                expect(restored.values.currentViewId).toBe('view-3')
                expect(restored.values.tagsFilter).toEqual(['calls'])
            } finally {
                restored.unmount()
            }
        })

        it('"All notes" clears the tile back to newest first, its own default', async () => {
            await expectLogic(tileViewsLogic).toFinishAllListeners()
            tileViewsLogic.actions.selectView('view-1')
            await expectLogic(tileLogic).toFinishAllListeners()
            expect(tileLogic.values.sorting).toEqual({ columnKey: 'title', order: 1 })

            tileViewsLogic.actions.clearView()
            await expectLogic(tileViewsLogic).toFinishAllListeners()
            await expectLogic(tileLogic).toFinishAllListeners()

            expect(tileViewsLogic.values.currentViewId).toBeNull()
            expect(tileLogic.values.tagsFilter).toEqual([])
            expect(tileLogic.values.sorting).toEqual({ columnKey: 'created_at', order: -1 })
            expect(mockNotebooksList).toHaveBeenLastCalledWith(
                expect.any(String),
                'acc-1',
                expect.objectContaining({ ordering: '-created_at', tags: undefined })
            )
        })
    })
})

describe('account notes view serialization', () => {
    it('round-trips a view state and tolerates missing or malformed fields', () => {
        const state = deserializeAccountNotesView(
            buildView({ filters: [] as unknown as ColumnConfigurationApi['filters'], order_by: ['bogus'] })
        )
        expect(state).toEqual({
            filters: {
                search: '',
                tags: [],
                created_by: [],
                assigned_to: [],
                account_id: null,
                account_name: null,
            },
            ordering: '-last_modified_at',
        })

        const full = deserializeAccountNotesView(
            buildView({
                filters: {
                    search: 'x',
                    tags: ['a', 1],
                    created_by: [1, 'two'],
                    assigned_to: [3],
                    account_id: 'acc',
                    account_name: 'Acme Example',
                },
                order_by: ['-title'],
            })
        )
        expect(serializeAccountNotesView(full)).toEqual({
            columns: ACCOUNT_NOTES_VIEW_COLUMNS,
            order_by: ['-title'],
            filters: {
                search: 'x',
                tags: ['a'],
                created_by: [1],
                assigned_to: [3],
                account_id: 'acc',
                account_name: 'Acme Example',
            },
        })
    })
})

describe('what a view saves', () => {
    const names: Record<number, string> = { 7: 'Leo', 9: 'Kaya' }
    const memberName = (id: number): string => names[id] ?? `user ${id}`
    const state = {
        filters: {
            search: ' renewal ',
            tags: ['account-plan', 'risk'],
            created_by: [7, 9],
            assigned_to: [9],
            account_id: 'acc',
            account_name: 'Acme Example',
        },
        ordering: '-title' as const,
    }

    it('lists every saved filter and the sort on the team Notes tab', () => {
        expect(describeAccountNotesView(state, memberName, 'notes_tab')).toEqual({
            applied: [
                'Tags: account-plan, risk',
                'Created by: Leo, Kaya',
                'Search: "renewal"',
                'Account: Acme Example',
                'Assigned to: Kaya',
                'Sort: Title, Z to A',
            ],
            teamTabOnly: [],
        })
    })

    it.each(['-title', 'account_name'] as const)(
        'marks team-only filters and ordering %s inside an account',
        (ordering) => {
            const summary = describeAccountNotesView({ ...state, ordering }, memberName, 'account')

            expect(summary.applied).not.toContain('Account: Acme Example')
            expect(summary.teamTabOnly).toEqual([
                'Account: Acme Example',
                'Assigned to: Kaya',
                ...(ordering === 'account_name' ? ['Sort: Account, A to Z'] : []),
            ])
            expect(summary.applied).toContain(
                ordering === 'account_name' ? 'Sort: Created, newest first' : 'Sort: Title, Z to A'
            )
        }
    )

    it('describes an empty view as just its sort', () => {
        const empty = deserializeAccountNotesView(buildView({ filters: {}, order_by: ['-created_at'] }))

        expect(describeAccountNotesView(empty, memberName, 'account')).toEqual({
            applied: ['Sort: Created, newest first'],
            teamTabOnly: [],
        })
    })
})
