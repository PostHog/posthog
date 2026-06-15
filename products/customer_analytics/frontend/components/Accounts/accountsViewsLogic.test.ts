import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { accountsLogic } from './accountsLogic'
import { accountsOverviewTilesLogic } from './accountsOverviewTilesLogic'
import { accountsViewsLogic } from './accountsViewsLogic'
import { DEFAULT_TILES } from './constants'

const CURRENT_USER_ID = MOCK_DEFAULT_USER.id

const buildView = (overrides: Partial<ColumnConfigurationApi> = {}): ColumnConfigurationApi =>
    ({
        id: 'view-1',
        context_key: 'customer_analytics_accounts_columns',
        columns: ['name', 'csm'],
        name: 'Enterprise',
        filters: { search: 'acme', csm: [1] },
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
        userLogic.mount()
    })

    it('lists views on mount', async () => {
        useMocks({ get: { '/api/environments/:team_id/column_configurations/': { count: 1, results: [buildView()] } } })
        mountAll()
        await expectLogic(logic)
            .toDispatchActions(['loadViewsSuccess'])
            .toMatchValues({
                views: [expect.objectContaining({ id: 'view-1' })],
            })
    })

    it('applyView hydrates columns, filters, sort, and tiles', async () => {
        useMocks({ get: { '/api/environments/:team_id/column_configurations/': { count: 0, results: [] } } })
        mountAll()
        const view = buildView({
            filters: {
                search: 'acme',
                tags: ['enterprise'],
                unassigned: false,
                csm: [1],
                accountExecutive: [2],
                accountOwner: [3],
                tileFilter: { tileId: 't1', expression: 'mrr > 100' },
            },
        })
        await expectLogic(logic, () => logic.actions.applyView(view)).toFinishAllListeners()

        expect(accountsColumnConfigLogic.values.selectColumns).toEqual(['name', 'csm'])
        expect(accountsLogic.values.searchQuery).toEqual('acme')
        expect(accountsLogic.values.tagsFilter).toEqual(['enterprise'])
        expect(accountsLogic.values.allRolesUnassigned).toBe(false)
        expect(accountsLogic.values.csmFilter).toEqual([1])
        expect(accountsLogic.values.accountExecutiveFilter).toEqual([2])
        expect(accountsLogic.values.accountOwnerFilter).toEqual([3])
        expect(accountsLogic.values.sortOrder).toEqual({ column: 'csm', direction: 'desc' })
        expect(accountsOverviewTilesLogic.values.tiles).toEqual([
            { id: 't1', label: 'Accounts', metric: { type: 'count' } },
        ])
        expect(accountsOverviewTilesLogic.values.tileFilter).toEqual({ tileId: 't1', expression: 'mrr > 100' })
        expect(logic.values.currentViewId).toEqual('view-1')
    })

    it('isDirty flips when live state diverges from the applied view and clears on re-apply', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/column_configurations/': { count: 1, results: [buildView()] },
            },
        })
        mountAll()
        // Wait for loadViewsSuccess so the view is in views, then select it
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])
        logic.actions.applyView(buildView())
        await expectLogic(logic).toMatchValues({ isDirty: false })

        accountsLogic.actions.setSearchQuery('changed')
        await expectLogic(logic).toMatchValues({ isDirty: true })

        logic.actions.applyView(buildView())
        await expectLogic(logic).toMatchValues({ isDirty: false })
    })

    it('deleteView clears currentViewId when the active view is removed', async () => {
        useMocks({
            get: { '/api/environments/:team_id/column_configurations/': { count: 1, results: [buildView()] } },
            delete: { '/api/environments/:team_id/column_configurations/:id/': [204] },
        })
        mountAll()
        await expectLogic(logic).toDispatchActions(['loadViewsSuccess'])
        logic.actions.applyView(buildView())
        await expectLogic(logic, () => logic.actions.deleteView({ id: 'view-1' }))
            .toDispatchActions(['deleteViewSuccess'])
            .toMatchValues({ currentViewId: null })
    })

    it('migrates localStorage tiles into the creator-owned default row exactly once', async () => {
        const customTiles = [{ id: 'mine', label: 'Mine', metric: { type: 'count' as const } }]
        let patchedBody: any = null
        useMocks({
            get: {
                '/api/environments/:team_id/column_configurations/': {
                    count: 1,
                    results: [buildView({ properties: {} })],
                },
            },
            patch: {
                '/api/environments/:team_id/column_configurations/:id/': async (req: any) => {
                    patchedBody = await req.json()
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
                '/api/environments/:team_id/column_configurations/': {
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
                '/api/environments/:team_id/column_configurations/': {
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
})
