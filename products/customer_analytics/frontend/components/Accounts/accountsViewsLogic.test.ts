import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import type { AccountsTableQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { ACCOUNTS_DEFAULT_COLUMNS, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { accountsLogic, SEARCH_DEBOUNCE_MS } from './accountsLogic'
import { accountsOverviewTilesLogic } from './accountsOverviewTilesLogic'
import { accountsViewsLogic } from './accountsViewsLogic'
import { readAccountsViewDraft, type AccountsViewState, writeAccountsViewDraft } from './accountsViewState'
import { DEFAULT_TILES } from './constants'

const CURRENT_USER_ID = MOCK_DEFAULT_USER.id

const buildView = (overrides: Partial<ColumnConfigurationApi> = {}): ColumnConfigurationApi =>
    ({
        id: 'view-1',
        context_key: 'customer_analytics_accounts_columns',
        columns: ['name', 'csm'],
        name: 'Enterprise',
        filters: { search: 'acme', assignedTo: [1] },
        order_by: ['csm DESC'],
        properties: { tiles: [{ id: 't1', label: 'Accounts', metric: { type: 'count' } }] },
        visibility: 'shared',
        created_by: CURRENT_USER_ID,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    }) as ColumnConfigurationApi

describe('accountsViewsLogic', () => {
    let logic: ReturnType<typeof accountsViewsLogic.build>

    const mountAll = (): void => {
        accountsColumnConfigLogic().mount()
        accountsOverviewTilesLogic().mount()
        accountsLogic().mount()
        logic = accountsViewsLogic()
        logic.mount()
    }

    beforeEach(() => {
        // Set up POSTHOG_APP_CONTEXT with MOCK_DEFAULT_USER before initKeaTests so
        // the user is pre-loaded (mirrors how the app bootstraps in production).
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            current_team: MOCK_DEFAULT_TEAM,
            current_user: MOCK_DEFAULT_USER,
        } as any
        initKeaTests()
        router.actions.push(urls.customerAnalyticsAccounts())
        sessionStorage.clear()
        userLogic.mount()
    })

    afterEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        jest.useRealTimers()
    })

    it('lists views on mount', async () => {
        useMocks({ get: { '/api/projects/:team_id/column_configurations/': { count: 1, results: [buildView()] } } })
        mountAll()
        await expectLogic(logic)
            .toDispatchActions(['loadViewsSuccess'])
            .toMatchValues({
                views: [expect.objectContaining({ id: 'view-1' })],
            })
    })

    it('holds the first accounts fetch until a delayed draft decision permits the persisted view', async () => {
        useMocks({ get: { '/api/projects/:team_id/column_configurations/': { count: 1, results: [buildView()] } } })
        localStorage.setItem(
            `customerAnalytics.accounts.accountsViewsLogic.${MOCK_DEFAULT_TEAM.id}.currentViewId`,
            JSON.stringify('view-1')
        )
        accountsColumnConfigLogic().mount()
        accountsOverviewTilesLogic().mount()
        accountsLogic().mount()
        accountsLogic.actions.setViewStateHydrated(false)
        logic = accountsViewsLogic()
        logic.mount()

        expect(accountsLogic.values.awaitingSavedView).toBe(true)
        expect(accountsLogic.values.accountsQuerySource).toBeNull()
        expect(accountsLogic.values.metricsQuery).toBeNull()

        await expectLogic(logic).toDispatchActions(['loadViewsSuccess', 'restoreSavedView']).toFinishAllListeners()

        expect(accountsLogic.values.awaitingSavedView).toBe(true)
        expect(accountsLogic.values.searchQuery).toBe('')

        await expectLogic(logic, () => accountsLogic.actions.setViewStateHydrated(true))
            .toDispatchActions(['restoreSavedView', 'applyView'])
            .toFinishAllListeners()

        expect(accountsLogic.values.awaitingSavedView).toBe(false)
        expect(accountsColumnConfigLogic.values.selectColumns).toEqual(['name', 'csm'])
        expect(accountsLogic.values.searchQuery).toEqual('acme')
    })

    it.each([
        [false, 'views', true],
        [true, 'views', true],
        [false, 'relationships', true],
        [true, 'relationships', true],
        [true, 'views', false],
        [true, 'relationships', false],
    ] as const)(
        'restores a fresh tab with mineOnly=%s, %s loading first, and savedView=%s',
        async (mineOnly, firstResponse, savedView) => {
            customerAnalyticsSceneLogic.mount()
            customerAnalyticsSceneLogic.actions.setMineOnly(mineOnly)
            let releaseViews!: () => void
            let releaseRelationships!: () => void
            const viewsReady = new Promise<void>((resolve) => {
                releaseViews = resolve
            })
            const relationshipsReady = new Promise<void>((resolve) => {
                releaseRelationships = resolve
            })
            useMocks({
                get: {
                    '/api/projects/:team_id/column_configurations/': async () => {
                        await viewsReady
                        return { count: 1, results: [buildView()] }
                    },
                    '/api/projects/:team_id/account_relationship_definitions/': async () => {
                        await relationshipsReady
                        return {
                            count: 1,
                            results: [
                                {
                                    id: '11111111-2222-3333-4444-555555555555',
                                    name: 'CSM',
                                    description: null,
                                    is_single_holder: true,
                                },
                            ],
                        }
                    },
                },
            })
            if (savedView) {
                localStorage.setItem(
                    `customerAnalytics.accounts.accountsViewsLogic.${MOCK_DEFAULT_TEAM.id}.currentViewId`,
                    JSON.stringify('view-1')
                )
            }
            mountAll()

            if (firstResponse === 'views') {
                releaseViews()
                await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])
                releaseRelationships()
            } else {
                releaseRelationships()
                await expectLogic(accountsColumnConfigLogic).toDispatchActions(['loadRelationshipDefinitionsSuccess'])
                releaseViews()
            }
            await expectLogic(logic).toFinishAllListeners()

            expect(accountsColumnConfigLogic.values.selectColumns).toEqual(
                savedView ? ['name', 'csm'] : [...ACCOUNTS_DEFAULT_COLUMNS, 'csm']
            )
            expect(accountsLogic.values.searchQuery).toBe(savedView ? 'acme' : '')
            expect(accountsLogic.values.assignedToFilter).toEqual(savedView ? [1] : [CURRENT_USER_ID])
            expect(accountsLogic.values.awaitingSavedView).toBe(false)
            expect(logic.values.currentViewId).toBe(savedView ? 'view-1' : null)
            expect(logic.values.isDirty).toBe(false)
            if (!savedView) {
                expect(readAccountsViewDraft(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid)).toBeNull()
            }
        }
    )

    it('opens the gate when loading views fails, so the list still fetches', async () => {
        useMocks({ get: { '/api/projects/:team_id/column_configurations/': () => [500, {}] } })
        localStorage.setItem(
            `customerAnalytics.accounts.accountsViewsLogic.${MOCK_DEFAULT_TEAM.id}.currentViewId`,
            JSON.stringify('view-1')
        )
        silenceKeaLoadersErrors()
        try {
            mountAll()
            expect(accountsLogic.values.awaitingSavedView).toBe(true)
            await expectLogic(logic).toDispatchActions(['loadViewsFailure'])
            expect(accountsLogic.values.awaitingSavedView).toBe(false)
        } finally {
            resumeKeaLoadersErrors()
        }
    })

    it('applyView hydrates columns, filters, sort, and tiles', async () => {
        useMocks({ get: { '/api/projects/:team_id/column_configurations/': { count: 0, results: [] } } })
        mountAll()
        const view = buildView({
            filters: {
                search: 'acme',
                tags: ['enterprise'],
                assignmentStatus: 'assigned',
                assignedTo: [1, 2, 3],
                tileFilter: {
                    tileId: 't1',
                    filter: {
                        kind: 'custom_property',
                        definitionId: '11111111-2222-3333-4444-555555555555',
                        operator: 'gt',
                        values: [100],
                    },
                },
            },
        })
        await expectLogic(logic, () => logic.actions.applyView(view)).toFinishAllListeners()

        expect(accountsColumnConfigLogic.values.selectColumns).toEqual(['name', 'csm'])
        expect(accountsLogic.values.searchQuery).toEqual('acme')
        expect(accountsLogic.values.tagsFilter).toEqual(['enterprise'])
        expect(accountsLogic.values.assignmentStatus).toBe('assigned')
        expect(accountsLogic.values.assignedToFilter).toEqual([1, 2, 3])
        expect(accountsLogic.values.sortOrder).toEqual({ column: 'csm', direction: 'desc' })
        expect(accountsOverviewTilesLogic.values.tiles).toEqual([
            { id: 't1', label: 'Accounts', metric: { type: 'count' } },
        ])
        expect(accountsOverviewTilesLogic.values.tileFilter).toEqual({
            tileId: 't1',
            filter: {
                kind: 'custom_property',
                definitionId: '11111111-2222-3333-4444-555555555555',
                operator: 'gt',
                values: [100],
            },
        })
        expect(logic.values.currentViewId).toEqual('view-1')
    })

    it('translates an applied saved view into the Postgres query', async () => {
        useMocks({ get: { '/api/projects/:team_id/column_configurations/': { count: 0, results: [] } } })
        mountAll()
        await expectLogic(logic, () =>
            logic.actions.applyView(
                buildView({
                    columns: ['name'],
                    filters: { search: 'acme', tags: ['enterprise'], assignedTo: [1, 2] },
                    order_by: ['name DESC'],
                })
            )
        ).toFinishAllListeners()

        const source = accountsLogic.values.accountsQuerySource as AccountsTableQuery
        expect(source.kind).toBe('AccountsTableQuery')
        expect(source.columns).toEqual([{ kind: 'account_field', field: 'name' }])
        expect(source.filters).toEqual([
            { kind: 'search', query: 'acme' },
            { kind: 'tags', tagNames: ['enterprise'] },
            { kind: 'assigned_to', userIds: [1, 2] },
        ])
    })

    it('applies a legacy saved view (no assignment field) as assigned-only', async () => {
        useMocks({ get: { '/api/projects/:team_id/column_configurations/': { count: 0, results: [] } } })
        mountAll()
        // A view saved before the status field existed must not silently broaden to all.
        await expectLogic(logic, () =>
            logic.actions.applyView(buildView({ columns: ['name'], filters: { search: 'acme' } }))
        ).toFinishAllListeners()

        expect(accountsLogic.values.assignmentStatus).toBe('assigned')
        const source = accountsLogic.values.accountsQuerySource as AccountsTableQuery
        expect(source.filters).toContainEqual({ kind: 'assigned' })
    })

    it('keeps column widths when the selected view changes', async () => {
        useMocks({ get: { '/api/projects/:team_id/column_configurations/': { count: 0, results: [] } } })
        mountAll()

        logic.actions.setColumnWidth('name', 320)
        logic.actions.setCurrentViewId('view-1')

        await expectLogic(logic).toMatchValues({ columnWidths: { name: 320 } })
    })

    it('keeps dirty edits over automatic saved-view restore, then replaces them when the user selects the view', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/column_configurations/': { count: 1, results: [buildView()] },
            },
        })
        mountAll()
        // Wait for loadViewsSuccess so the view is in views, then select it.
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])
        logic.actions.applyView(buildView())
        await expectLogic(logic).toMatchValues({ isDirty: false })

        accountsLogic.actions.setSearchQuery('changed')
        await expectLogic(logic).toMatchValues({ isDirty: true })

        logic.unmount()
        accountsLogic.findMounted()?.unmount()
        accountsOverviewTilesLogic.findMounted()?.unmount()
        accountsColumnConfigLogic.findMounted()?.unmount()
        router.actions.push(urls.customerAnalyticsAccounts())
        mountAll()
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])

        expect(accountsLogic.values.searchQuery).toBe('changed')
        expect(logic.values.isDirty).toBe(true)

        jest.useFakeTimers()
        accountsLogic.actions.setSearchInput('stale search')
        logic.actions.selectView('view-1')
        await jest.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS)
        await expectLogic(logic).toFinishAllListeners()

        expect(accountsLogic.values.searchQuery).toBe('acme')
        expect(logic.values.isDirty).toBe(false)

        logic.unmount()
        accountsLogic.findMounted()?.unmount()
        accountsOverviewTilesLogic.findMounted()?.unmount()
        accountsColumnConfigLogic.findMounted()?.unmount()
        router.actions.push(urls.customerAnalyticsAccounts())
        mountAll()
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])

        expect(accountsLogic.values.searchQuery).toBe('acme')
        expect(logic.values.isDirty).toBe(false)
    })

    it('keeps a cleared all-default draft instead of auto-applying the selected saved view', async () => {
        const clearedDraft: AccountsViewState = {
            columns: [...ACCOUNTS_DEFAULT_COLUMNS],
            sortOrder: null,
            filters: {
                search: '',
                assignmentStatus: 'all',
                assignedTo: [],
                tags: [],
                tileFilter: null,
                customProperties: [],
            },
            tiles: [...DEFAULT_TILES],
            columnDisplay: {},
        }
        writeAccountsViewDraft(MOCK_DEFAULT_TEAM.id, MOCK_DEFAULT_USER.uuid, clearedDraft)
        localStorage.setItem(
            `customerAnalytics.accounts.accountsViewsLogic.${MOCK_DEFAULT_TEAM.id}.currentViewId`,
            JSON.stringify('view-1')
        )
        useMocks({
            get: {
                '/api/projects/:team_id/column_configurations/': { count: 1, results: [buildView()] },
            },
        })
        mountAll()
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])

        expect(accountsLogic.values.searchQuery).toBe('')
        expect(accountsLogic.values.assignmentStatus).toBe('all')
        expect(logic.values.currentViewId).toBe('view-1')
        expect(logic.values.isDirty).toBe(true)
    })

    it('deleteView clears currentViewId when the active view is removed', async () => {
        useMocks({
            get: { '/api/projects/:team_id/column_configurations/': { count: 1, results: [buildView()] } },
            delete: { '/api/projects/:team_id/column_configurations/:id/': [204] },
        })
        mountAll()
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])
        logic.actions.applyView(buildView())
        await expectLogic(logic, () => logic.actions.deleteView({ id: 'view-1' }))
            .toDispatchActions(['deleteViewSuccess'])
            .toMatchValues({ currentViewId: null })
    })

    it('creates a view from the current state', async () => {
        let createdBody: Record<string, unknown> | null = null
        useMocks({
            get: { '/api/projects/:team_id/column_configurations/': { count: 0, results: [] } },
            post: {
                '/api/projects/:team_id/column_configurations/': async ({ request }) => {
                    createdBody = (await request.json()) as Record<string, unknown>
                    return [201, buildView({ name: 'New view', visibility: 'private' })]
                },
            },
        })
        mountAll()
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])

        logic.actions.setViewFormValues({ name: '  New view  ', visibility: 'private' })
        await expectLogic(logic, () => logic.actions.submitViewForm()).toDispatchActions([
            'applyView',
            'submitViewFormSuccess',
        ])

        expect(createdBody).toEqual(
            expect.objectContaining({
                context_key: 'customer_analytics_accounts_columns',
                name: 'New view',
                visibility: 'private',
            })
        )
    })

    it('edit seeds the form and patches the trimmed name and visibility', async () => {
        let patchedBody: Record<string, unknown> | null = null
        const sharedView = buildView({ created_by: 999 })
        useMocks({
            get: { '/api/projects/:team_id/column_configurations/': { count: 1, results: [sharedView] } },
            patch: {
                '/api/projects/:team_id/column_configurations/:id/': async ({ request }) => {
                    patchedBody = (await request.json()) as Record<string, unknown>
                    return [200, buildView({ created_by: CURRENT_USER_ID, name: 'Renamed', visibility: 'private' })]
                },
            },
        })
        mountAll()
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])
        logic.actions.applyView(sharedView)
        expect(logic.values.canEditCurrentView).toBe(true)

        await expectLogic(logic, () => logic.actions.setViewToEdit('view-1'))
            .toDispatchActions(['setViewFormValues'])
            .toMatchValues({
                viewToEdit: 'view-1',
                viewForm: { name: 'Enterprise', visibility: 'shared' },
            })

        logic.actions.setViewFormValues({ name: '  Renamed  ', visibility: 'private' })
        await expectLogic(logic, () => logic.actions.submitViewForm())
            .toDispatchActions(['updateView', 'updateViewSuccess'])
            .toMatchValues({ viewToEdit: null })
        expect(patchedBody).toEqual({ name: 'Renamed', visibility: 'private' })
    })

    it('migrates localStorage tiles into the creator-owned default row exactly once', async () => {
        const customTiles = [{ id: 'mine', label: 'Mine', metric: { type: 'count' as const } }]
        let patchedBody: any = null
        useMocks({
            get: {
                '/api/projects/:team_id/column_configurations/': {
                    count: 1,
                    results: [buildView({ properties: {} })],
                },
            },
            patch: {
                '/api/projects/:team_id/column_configurations/:id/': async ({ request }) => {
                    patchedBody = await request.json()
                    return [200, buildView({ properties: patchedBody.properties })]
                },
            },
        })
        accountsColumnConfigLogic().mount()
        accountsOverviewTilesLogic().mount()
        accountsOverviewTilesLogic.actions.setTiles(customTiles)
        accountsLogic().mount()
        logic = accountsViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions([
            'loadViewsSuccess',
            'patchViewProperties',
            'patchViewPropertiesSuccess',
        ])
        expect(patchedBody.properties).toEqual({ tiles: customTiles })
    })

    it('does not migrate when localStorage tiles are the defaults', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/column_configurations/': {
                    count: 1,
                    results: [buildView({ properties: {} })],
                },
            },
        })
        accountsColumnConfigLogic().mount()
        accountsOverviewTilesLogic().mount()
        accountsOverviewTilesLogic.actions.setTiles([...DEFAULT_TILES])
        accountsLogic().mount()
        logic = accountsViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadViewsSuccess']).toFinishAllListeners()
        expect(logic.values.views[0].properties).toEqual({})
    })

    it('does not migrate into a row the user did not create', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/column_configurations/': {
                    count: 1,
                    results: [buildView({ properties: {}, created_by: 999 })],
                },
            },
        })
        accountsColumnConfigLogic().mount()
        accountsOverviewTilesLogic().mount()
        accountsOverviewTilesLogic.actions.setTiles([{ id: 'mine', label: 'Mine', metric: { type: 'count' as const } }])
        accountsLogic().mount()
        logic = accountsViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadViewsSuccess']).toFinishAllListeners()
        expect(logic.values.views[0].properties).toEqual({})
    })

    it('preserves migrated tiles when the migrated row is the restored current view', async () => {
        const customTiles = [{ id: 'mine', label: 'Mine', metric: { type: 'count' as const } }]
        localStorage.setItem(
            `customerAnalytics.accounts.accountsViewsLogic.${MOCK_DEFAULT_TEAM.id}.currentViewId`,
            JSON.stringify('view-1')
        )
        useMocks({
            get: {
                '/api/projects/:team_id/column_configurations/': {
                    count: 1,
                    results: [buildView({ properties: {} })],
                },
            },
            patch: {
                '/api/projects/:team_id/column_configurations/:id/': async ({ request }) => {
                    const body = (await request.json()) as any
                    return [200, buildView({ properties: body.properties })]
                },
            },
        })
        accountsColumnConfigLogic().mount()
        accountsOverviewTilesLogic().mount()
        accountsOverviewTilesLogic.actions.setTiles(customTiles)
        accountsLogic().mount()
        logic = accountsViewsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadViewsSuccess', 'patchViewProperties', 'applyView'])
        expect(accountsOverviewTilesLogic.values.tiles).toEqual(customTiles)
    })
})
