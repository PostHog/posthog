import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    columnConfigurationsCreate,
    columnConfigurationsDestroy,
    columnConfigurationsList,
    columnConfigurationsPartialUpdate,
} from 'products/product_analytics/frontend/generated/api'
import type { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { ACCOUNTS_DEFAULT_COLUMNS, ACCOUNTS_TAGS_COLUMN, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { accountsLogic, SEARCH_DEBOUNCE_MS } from './accountsLogic'
import { accountsOverviewTilesLogic } from './accountsOverviewTilesLogic'
import { getAccountsBackUrl } from './accountsViewSessionLogic'
import { accountsViewsLogic } from './accountsViewsLogic'
import { accountsViewIdStorageKey, deserializeAccountsView, readAccountsViewId } from './accountsViewState'
import { ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX, AccountsEvents, DEFAULT_TILES } from './constants'

jest.mock('products/product_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/product_analytics/frontend/generated/api'),
    columnConfigurationsCreate: jest.fn(),
    columnConfigurationsDestroy: jest.fn(),
    columnConfigurationsList: jest.fn(),
    columnConfigurationsPartialUpdate: jest.fn(),
}))

const mockList = jest.mocked(columnConfigurationsList)
const mockCreate = jest.mocked(columnConfigurationsCreate)
const mockDelete = jest.mocked(columnConfigurationsDestroy)
const mockUpdate = jest.mocked(columnConfigurationsPartialUpdate)
const scopedKey = accountsViewIdStorageKey(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid)
const legacyKey = `customerAnalytics.accounts.accountsViewsLogic.${MOCK_DEFAULT_TEAM.id}.currentViewId`
const accountId = '0190da51-0b0e-7000-8000-000000000001'

const buildView = (overrides: Partial<ColumnConfigurationApi> = {}): ColumnConfigurationApi => ({
    id: 'view-1',
    context_key: 'customer_analytics_accounts_columns',
    columns: ['name', 'csm'],
    name: 'Enterprise',
    filters: { search: 'example', assignmentStatus: 'assigned', assignedTo: [1] },
    order_by: ['csm DESC'],
    properties: { tiles: [{ id: 't1', label: 'Accounts', metric: { type: 'count' } }] },
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

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('accountsViewsLogic', () => {
    let logic: ReturnType<typeof accountsViewsLogic.build>

    const mount = (): void => {
        logic = accountsViewsLogic()
        logic.mount()
    }
    const settle = async (): Promise<void> => {
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(accountsColumnConfigLogic).toFinishAllListeners()
        await expectLogic(accountsLogic).toFinishAllListeners()
    }
    const reload = (): void => {
        logic.unmount()
        initKeaTests()
        userLogic.mount()
        router.actions.push(urls.customerAnalyticsAccounts())
        mount()
    }

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            current_team: MOCK_DEFAULT_TEAM,
            current_user: MOCK_DEFAULT_USER,
        } as any
        initKeaTests()
        userLogic.mount()
        router.actions.push(urls.customerAnalyticsAccounts())
        mockList.mockReset().mockResolvedValue(response([buildView()]))
        mockCreate.mockReset()
        mockDelete.mockReset().mockResolvedValue(undefined)
        mockUpdate.mockReset()
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
        sessionStorage.clear()
        jest.useRealTimers()
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
    })

    it.each([scopedKey, legacyKey])(
        'restores the current server definition from %s, ignoring storage snapshots',
        async (key) => {
            localStorage.setItem(key, JSON.stringify('view-1'))
            const draftKey = `customerAnalytics.accounts.viewDraft.${MOCK_DEFAULT_TEAM.id}.${MOCK_DEFAULT_USER.uuid}`
            const staleDraft = JSON.stringify(
                deserializeAccountsView(buildView({ filters: { search: 'stale draft' } }))
            )
            sessionStorage.setItem(draftKey, staleDraft)
            localStorage.setItem(draftKey, staleDraft)
            const capture = jest.spyOn(posthog, 'capture')
            mount()
            await settle()
            expect(accountsLogic.values.searchQuery).toBe('example')
            expect(logic.values.isDirty).toBe(false)
            expect(router.values.searchParams.view).toBe('view-1')
            expect(router.values.hashParams.view).toBeUndefined()
            expect(JSON.parse(localStorage.getItem(scopedKey)!)).toEqual({ id: 'view-1', name: 'Enterprise' })
            expect(localStorage.getItem(legacyKey)).toBeNull()
            expect(capture).toHaveBeenCalledWith(AccountsEvents.ViewSelected, { visibility: 'shared' })

            accountsLogic.actions.setSearchQuery('unsaved')
            accountsLogic.actions.setTagsFilter(['draft'])
            expect(sessionStorage.getItem(draftKey)).toBe(staleDraft)
            expect(localStorage.getItem(draftKey)).toBe(staleDraft)
            const updated = buildView({
                name: 'Renamed elsewhere',
                columns: ['name'],
                filters: { search: 'fresh server', assignmentStatus: 'all' },
            })
            mockList.mockResolvedValue(response([updated]))
            reload()
            await settle()
            expect(accountsLogic.values.searchQuery).toBe('fresh server')
            expect(accountsLogic.values.tagsFilter).toEqual([])
            expect(accountsColumnConfigLogic.values.selectColumns).toEqual(['name'])
            expect(logic.values.currentView?.name).toBe('Renamed elsewhere')
            expect(logic.values.currentViewName).toBe('Renamed elsewhere')
            expect(JSON.parse(localStorage.getItem(scopedKey)!)).toEqual({ id: 'view-1', name: 'Renamed elsewhere' })
            expect(logic.values.isDirty).toBe(false)
        }
    )

    it.each([
        [false, false],
        [true, false],
        [false, true],
        [true, true],
    ] as const)(
        'prefers an explicit ID over the remembered ID and legacy hash (missing=%s, detail=%s)',
        async (missing, detail) => {
            localStorage.setItem(scopedKey, JSON.stringify('view-1'))
            const path = detail ? urls.customerAnalyticsAccount(accountId, 'usage') : urls.customerAnalyticsAccounts()
            router.actions.push(
                path,
                { view: 'view-2', date_from: '-30d', filter_test_accounts: 'true' },
                { view: { search: 'legacy' } }
            )
            const unrelatedSearch = Object.fromEntries(new URLSearchParams(router.values.location.search))
            delete unrelatedSearch.view
            const linked = buildView({ id: 'view-2', filters: { search: 'linked', assignmentStatus: 'all' } })
            mockList.mockResolvedValue(response(missing ? [buildView()] : [buildView(), linked]))
            mount()
            await settle()
            expect(accountsLogic.values.searchQuery).toBe(missing ? '' : 'linked')
            expect(logic.values.currentViewId).toBe(missing ? null : 'view-2')
            expect(Object.fromEntries(new URLSearchParams(router.values.location.search))).toEqual({
                ...unrelatedSearch,
                ...(missing ? {} : { view: 'view-2' }),
            })
            expect(router.values.location.pathname.endsWith(path)).toBe(true)
            expect(router.values.hashParams.view).toBeUndefined()
            expect(logic.values.isDirty).toBe(false)
            expect(readAccountsViewId(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid)).toBe(missing ? 'view-1' : 'view-2')
            if (missing) {
                reload()
                await settle()
                expect(logic.values.currentViewId).toBe('view-1')
                expect(accountsLogic.values.searchQuery).toBe('example')
            }
        }
    )

    it.each([true, false])(
        'hydrates a cached picker name and clears a missing cached view (exists=%s)',
        async (exists) => {
            localStorage.setItem(scopedKey, JSON.stringify({ id: 'view-1', name: 'Cached name' }))
            const pending = deferred<Awaited<ReturnType<typeof columnConfigurationsList>>>()
            mockList.mockReturnValue(pending.promise)
            mount()
            expect(logic.values.currentViewId).toBe('view-1')
            expect(logic.values.currentViewName).toBe('Cached name')
            expect(logic.values.viewsLoaded).toBe(false)
            expect(logic.values.currentView).toBeNull()
            expect(accountsLogic.values.accountsQuerySource).toBeNull()
            expect(logic.values.isDirty).toBe(false)

            await expectLogic(logic, () =>
                pending.resolve(response(exists ? [buildView({ name: 'Current name' })] : []))
            ).toDispatchActions(['loadViewsSuccess'])
            await settle()
            expect(logic.values.currentViewId).toBe(exists ? 'view-1' : null)
            expect(logic.values.currentViewName).toBe(exists ? 'Current name' : null)
            expect(logic.values.viewsLoaded).toBe(true)
            expect(logic.values.isDirty).toBe(false)
            expect(JSON.parse(localStorage.getItem(scopedKey)!)).toEqual(
                exists ? { id: 'view-1', name: 'Current name' } : null
            )
        }
    )

    it('finds an explicit saved view beyond the first page', async () => {
        router.actions.push(urls.customerAnalyticsAccounts(), { view: 'view-2' })
        mockList
            .mockResolvedValueOnce({ ...response([buildView()]), count: 2, next: 'next-page' })
            .mockResolvedValueOnce(response([buildView({ id: 'view-2', filters: { search: 'second page' } })]))
        mount()
        await settle()
        expect(logic.values.currentViewId).toBe('view-2')
        expect(accountsLogic.values.searchQuery).toBe('second page')
    })

    it('consumes a legacy snapshot without saving it or letting it override later selections', async () => {
        const remembered = { id: 'view-1', name: 'Enterprise' }
        localStorage.setItem(scopedKey, JSON.stringify(remembered))
        router.actions.push(
            urls.customerAnalyticsAccounts(),
            {},
            { view: { search: 'legacy', columns: ['name'], assignedTo: [7] } }
        )
        mount()
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('legacy')
        expect(accountsLogic.values.assignedToFilter).toEqual([7])
        expect(router.values.hashParams.view).toBeUndefined()
        expect(mockUpdate).not.toHaveBeenCalled()
        expect(mockCreate).not.toHaveBeenCalled()
        expect(JSON.parse(localStorage.getItem(scopedKey)!)).toEqual(remembered)
        logic.actions.selectView('view-1')
        await settle()
        router.actions.push(urls.customerAnalyticsAccount(accountId), router.values.searchParams)
        router.actions.push(urls.customerAnalyticsAccounts(), router.values.searchParams)
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('example')
        expect(router.values.searchParams.view).toBe('view-1')
    })

    it.each(['edit', 'select', 'navigate'] as const)(
        'does not let a slow restore replace a newer %s',
        async (action) => {
            localStorage.setItem(scopedKey, JSON.stringify('view-1'))
            const pending = deferred<Awaited<ReturnType<typeof columnConfigurationsList>>>()
            mockList.mockReturnValue(pending.promise)
            mount()
            expect(accountsLogic.values.accountsQuerySource).toBeNull()
            expect(accountsLogic.values.metricsQuery).toBeNull()
            expect(logic.values.isDirty).toBe(false)
            if (action === 'edit') {
                accountsLogic.actions.setSearchInput('typed while loading')
            } else if (action === 'select') {
                logic.actions.applyView(buildView({ id: 'view-2', filters: { search: 'new selection' } }))
                accountsLogic.actions.setTagsFilter(['edited selection'])
            } else {
                router.actions.push(urls.customerAnalyticsAccounts(), { view: 'view-2' })
            }
            await expectLogic(logic, () =>
                pending.resolve(
                    response([buildView(), buildView({ id: 'view-2', filters: { search: 'new selection' } })])
                )
            ).toDispatchActions(['loadViewsSuccess'])
            await settle()
            expect(accountsLogic.values.searchInput).toBe(action === 'edit' ? 'typed while loading' : 'new selection')
            expect(accountsLogic.values.tagsFilter).toEqual(action === 'select' ? ['edited selection'] : [])
            expect(logic.values.currentViewId).toBe(action === 'edit' ? 'view-1' : 'view-2')
            expect(accountsLogic.values.awaitingSavedView).toBe(false)
        }
    )

    it('keeps restoration gated on load errors and retries without dirty defaults', async () => {
        localStorage.setItem(scopedKey, JSON.stringify('view-1'))
        mockList.mockRejectedValueOnce(new Error('offline'))
        silenceKeaLoadersErrors()
        mount()
        await expectLogic(logic).toDispatchActions(['loadViewsFailure'])
        expect(logic.values.viewsLoadError).toBe(true)
        expect(logic.values.isDirty).toBe(false)
        expect(accountsLogic.values.accountsQuerySource).toBeNull()
        expect(accountsLogic.values.metricsQuery).toBeNull()
        await expectLogic(logic, () => logic.actions.loadViews()).toDispatchActions(['loadViewsSuccess'])
        expect(logic.values.viewsLoadError).toBe(false)
        expect(accountsLogic.values.searchQuery).toBe('example')
        expect(logic.values.isDirty).toBe(false)
    })

    it('retains edits through the account Back link, metadata saves, and list reloads, but explicit selection replaces them', async () => {
        mount()
        await settle()
        logic.actions.selectView('view-1')
        accountsLogic.actions.setSearchQuery('changed')
        const renamed = buildView({ name: 'Renamed' })
        const pendingSave = deferred<ColumnConfigurationApi>()
        mockUpdate.mockReturnValue(pendingSave.promise)
        logic.actions.updateView({ id: 'view-1', updates: { name: 'Renamed' } })
        accountsLogic.actions.setSearchQuery('changed during save')
        await expectLogic(logic, () => pendingSave.resolve(renamed)).toDispatchActions(['updateViewSuccess'])
        expect(accountsLogic.values.searchQuery).toBe('changed during save')
        const pendingReload = deferred<Awaited<ReturnType<typeof columnConfigurationsList>>>()
        mockList.mockReturnValueOnce(pendingReload.promise).mockResolvedValue(response([renamed]))
        logic.actions.loadViews()
        accountsLogic.actions.setSearchQuery('changed during reload')
        await expectLogic(logic, () => pendingReload.resolve(response([renamed]))).toDispatchActions([
            'loadViewsSuccess',
        ])
        expect(accountsLogic.values.searchQuery).toBe('changed during reload')
        expect(logic.values.currentView?.name).toBe('Renamed')
        expect(JSON.parse(localStorage.getItem(scopedKey)!)).toEqual({ id: 'view-1', name: 'Renamed' })
        expect(logic.values.isDirty).toBe(true)
        expect(router.values.searchParams.view).toBe('view-1')

        logic.actions.prepareAccountReturn()
        const backUrl = getAccountsBackUrl(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid)
        logic.unmount()
        expect(accountsLogic.findMounted()).toBeFalsy()
        router.actions.push(urls.customerAnalyticsAccount(accountId))
        router.actions.push(backUrl)
        mount()
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('changed during reload')
        expect(logic.values.isDirty).toBe(true)
        jest.useFakeTimers()
        accountsLogic.actions.setSearchInput('stale search')
        logic.actions.selectView('view-1')
        await jest.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
        expect(accountsLogic.values.searchQuery).toBe('example')
        expect(logic.values.isDirty).toBe(false)
    })

    it.each(['delete', 'inaccessible'] as const)(
        'clears a selected view after %s and retains column widths',
        async (kind) => {
            mount()
            await settle()
            logic.actions.selectView('view-1')
            logic.actions.setColumnWidth('name', 320)
            accountsLogic.actions.setSearchQuery('unsaved')
            if (kind === 'delete') {
                await expectLogic(logic, () => logic.actions.deleteView({ id: 'view-1' })).toDispatchActions([
                    'deleteViewSuccess',
                ])
            } else {
                mockList.mockResolvedValue(response([]))
                await expectLogic(logic, () => logic.actions.loadViews()).toDispatchActions(['loadViewsSuccess'])
            }
            expect(logic.values.currentViewId).toBeNull()
            expect(router.values.searchParams.view).toBeUndefined()
            expect(accountsLogic.values.searchQuery).toBe('')
            expect(logic.values.isDirty).toBe(false)
            expect(logic.values.columnWidths).toEqual({ name: 320 })
        }
    )

    it('uses ID history for back and forward without restoring snapshots', async () => {
        mockList.mockResolvedValue(response([buildView(), buildView({ id: 'view-2', filters: { search: 'second' } })]))
        mount()
        await settle()
        router.actions.push(urls.customerAnalyticsAccounts(), { view: 'view-1' })
        await settle()
        accountsLogic.actions.setSearchQuery('unsaved')
        router.actions.push(urls.customerAnalyticsAccounts(), { view: 'view-2' })
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('second')
        router.actions.locationChanged({
            ...router.values.currentLocation,
            url: `${urls.customerAnalyticsAccounts()}?view=view-1`,
            method: 'POP',
            pathname: urls.customerAnalyticsAccounts(),
            search: '?view=view-1',
            searchParams: { view: 'view-1' },
            hashParams: {},
        })
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('example')
        expect(logic.values.isDirty).toBe(false)
        router.actions.locationChanged({
            ...router.values.currentLocation,
            url: `${urls.customerAnalyticsAccounts()}?view=view-2`,
            method: 'POP',
            pathname: urls.customerAnalyticsAccounts(),
            search: '?view=view-2',
            searchParams: { view: 'view-2' },
            hashParams: {},
        })
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('second')
        accountsLogic.actions.setSearchQuery('unsaved sidebar')
        mockList.mockResolvedValue(response([buildView({ id: 'view-2', filters: { search: 'fresh second' } })]))
        router.actions.push(urls.customerAnalytics())
        router.actions.push(urls.customerAnalyticsAccounts())
        await settle()
        expect(logic.values.currentViewId).toBe('view-2')
        expect(accountsLogic.values.searchQuery).toBe('fresh second')
        expect(router.values.searchParams.view).toBe('view-2')
        expect(logic.values.isDirty).toBe(false)
    })

    it.each([true, false])('restores a one-use account Back return without URL snapshots (saved=%s)', async (saved) => {
        mount()
        await settle()
        if (saved) {
            logic.actions.selectView('view-1')
        }
        accountsLogic.actions.setSearchQuery('unsaved return')
        accountsLogic.actions.setTagsFilter(['draft tag'])
        logic.actions.prepareAccountReturn()
        const backUrl = getAccountsBackUrl(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid)
        const back = new URL(backUrl, 'http://localhost')
        expect(back.searchParams.get('view')).toBe(saved ? 'view-1' : null)
        expect(back.searchParams.get('restore_view')).toBeTruthy()
        expect(backUrl).not.toContain('unsaved')
        expect(back.hash).toBe('')

        logic.unmount()
        router.actions.push(urls.customerAnalyticsAccount(accountId))
        router.actions.push(backUrl)
        mount()
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('unsaved return')
        expect(accountsLogic.values.tagsFilter).toEqual(['draft tag'])
        expect(logic.values.currentViewId).toBe(saved ? 'view-1' : null)
        expect(router.values.searchParams.restore_view).toBeUndefined()

        accountsLogic.actions.setSearchQuery('later edit')
        router.actions.push(urls.customerAnalyticsNotes())
        router.actions.push(backUrl)
        await settle()
        expect(accountsLogic.values.searchQuery).toBe(saved ? 'example' : '')
        expect(accountsLogic.values.tagsFilter).toEqual([])
        expect(logic.values.isDirty).toBe(false)
        expect(router.values.searchParams.restore_view).toBeUndefined()
    })

    it('loads the current saved definition when returning from an account without unsaved changes', async () => {
        mount()
        await settle()
        logic.actions.selectView('view-1')
        logic.actions.prepareAccountReturn()
        const backUrl = getAccountsBackUrl(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid)
        logic.unmount()
        router.actions.push(urls.customerAnalyticsAccount(accountId))
        mockList.mockResolvedValue(response([buildView({ filters: { search: 'updated by teammate' } })]))
        router.actions.push(backUrl)
        mount()
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('updated by teammate')
        expect(logic.values.isDirty).toBe(false)
    })

    it('ignores a return token copied into a fresh app context', async () => {
        mount()
        await settle()
        logic.actions.selectView('view-1')
        accountsLogic.actions.setSearchQuery('unsaved return')
        logic.actions.prepareAccountReturn()
        const backUrl = getAccountsBackUrl(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid)
        logic.unmount()
        initKeaTests()
        userLogic.mount()
        router.actions.push(backUrl)
        mount()
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('example')
        expect(logic.values.isDirty).toBe(false)
        expect(router.values.searchParams.restore_view).toBeUndefined()
    })

    it('resets scoped memory on user and project changes and rejects an older project response', async () => {
        mount()
        await settle()
        logic.actions.selectView('view-1')
        accountsLogic.actions.setSearchQuery('private draft')
        const pending = deferred<Awaited<ReturnType<typeof columnConfigurationsList>>>()
        mockList.mockReturnValueOnce(pending.promise).mockResolvedValue(response([]))
        logic.actions.loadViews()
        await expectLogic(logic, () =>
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 })
        ).toDispatchActions(['loadViewsSuccess'])
        pending.resolve(response([buildView()]))
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('')
        expect(logic.values.currentViewId).toBeNull()
        expect(logic.values.views).toEqual([])
        await expectLogic(logic, () =>
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid: 'other-user' })
        ).toDispatchActions(['loadViewsSuccess'])
        expect(accountsLogic.values.searchQuery).toBe('')
        expect(logic.values.currentViewId).toBeNull()
        accountsLogic.actions.setSearchQuery('edits before leaving')
        logic.unmount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid: 'other-user' })
        mount()
        await settle()
        expect(accountsLogic.values.searchQuery).toBe('')
    })

    it('does not restore a persisted My accounts preference in a fresh Accounts view', async () => {
        customerAnalyticsSceneLogic.mount()
        customerAnalyticsSceneLogic.actions.setMineOnly(true)
        mockList.mockResolvedValue(response([]))
        mount()
        await settle()
        expect(accountsLogic.values.assignmentStatus).toBe('all')
        expect(accountsLogic.values.assignedToFilter).toEqual([])
        expect(customerAnalyticsSceneLogic.values.mineOnly).toBe(true)
    })

    it('normalizes legacy saved columns without marking the view dirty', async () => {
        const view = buildView({ columns: ['accounts.tags.account_id AS account_id', 'accounts.tags.names AS names'] })
        mockList.mockResolvedValue(response([view]))
        localStorage.setItem(scopedKey, JSON.stringify(view.id))
        mount()
        await settle()
        expect(accountsColumnConfigLogic.values.selectColumns).toEqual(['name', ACCOUNTS_TAGS_COLUMN])
        expect(logic.values.isDirty).toBe(false)
    })

    it('creates and updates views using the existing snapshot schema', async () => {
        const created = buildView({
            name: 'New view',
            visibility: 'private',
            columns: [...ACCOUNTS_DEFAULT_COLUMNS],
            order_by: [],
            filters: { search: 'current state', assignmentStatus: 'all' },
            properties: { tiles: [...DEFAULT_TILES] },
        })
        mockCreate.mockResolvedValue(created)
        mockList.mockResolvedValue(response([created]))
        mount()
        await settle()
        accountsLogic.actions.setSearchQuery('current state')
        logic.actions.setViewFormValues({ name: '  New view  ', visibility: 'private' })
        await expectLogic(logic, () => logic.actions.submitViewForm()).toDispatchActions(['submitViewFormSuccess'])
        expect(mockCreate).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({
                context_key: 'customer_analytics_accounts_columns',
                name: 'New view',
                visibility: 'private',
                filters: { search: 'current state', assignmentStatus: 'all' },
            })
        )
        accountsLogic.actions.setSearchQuery('content update')
        mockUpdate.mockResolvedValue(buildView({ filters: { search: 'content update', assignmentStatus: 'all' } }))
        await expectLogic(logic, () => logic.actions.updateView({ id: 'view-1', updates: {} })).toDispatchActions([
            'updateViewSuccess',
        ])
        expect(mockUpdate).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            'view-1',
            expect.objectContaining({ filters: { search: 'content update', assignmentStatus: 'all' } })
        )
    })

    it('does not migrate legacy tiles over a fetched server definition', async () => {
        mockList.mockResolvedValue(response([buildView({ properties: {} })]))
        localStorage.setItem(scopedKey, JSON.stringify('view-1'))
        localStorage.setItem(
            `${ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX}legacy.tiles`,
            JSON.stringify([{ id: 'mine', label: 'Mine', metric: { type: 'count' } }])
        )
        mount()
        await settle()
        expect(mockUpdate).not.toHaveBeenCalled()
        expect(accountsOverviewTilesLogic.values.tiles).toEqual(DEFAULT_TILES)
        expect(logic.values.isDirty).toBe(false)
    })
})
