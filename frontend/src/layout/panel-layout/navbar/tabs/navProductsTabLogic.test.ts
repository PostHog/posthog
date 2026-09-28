import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { DecideRequestApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { customProductsLogic } from '../../ProjectTree/customProductsLogic'
import { getDefaultTreeData, getDefaultTreeProducts } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { PRODUCTS_STARRED_TREE_KEY, SUGGESTED_GROUP_LABEL, navProductsTabLogic } from './navProductsTabLogic'
import { productsItemName, groupProducts } from './productsCatalog'

describe('navProductsTabLogic', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/file_system_shortcut/': { results: [] } } })
        initKeaTests()
        navProductsTabLogic.mount()
    })

    it.each([false, true])('retains every existing product and data destination with flags enabled: %s', (enabled) => {
        const registry = [...getDefaultTreeProducts(), ...getDefaultTreeData()]
        const flags = Object.fromEntries(registry.flatMap((item) => (item.flag ? [[item.flag, enabled]] : [])))
        const definitionsTabHrefs = new Set([
            urls.coreEvents(),
            urls.propertyDefinitions(),
            urls.schemaManagement(),
            urls.revenueSettings(),
            urls.warehouseProperties(),
        ])
        featureFlagLogic.actions.setFeatureFlags([], flags)
        const expected = new Set([
            urls.projectRoot(),
            urls.activity(ActivityTab.ExploreEvents),
            ...registry
                .filter((item) => item.href && (!item.flag || enabled) && !definitionsTabHrefs.has(item.href))
                .map((item) => item.href),
        ])
        const actual = [
            ...navProductsTabLogic.values.pinnedItems,
            ...navProductsTabLogic.values.groupedItems.flatMap((group) => group.items),
        ].map((item) => item.href)
        expect(new Set(actual)).toEqual(expected)
        expect(actual).toHaveLength(expected.size)
    })

    it('searches display names and sorts categories in a fixed order and products alphabetically', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true })
        expect(navProductsTabLogic.values.pinnedItems.map(productsItemName)).toEqual([
            'Home',
            'Self-driving',
            'Activity and people',
        ])
        expect(navProductsTabLogic.values.configurableProducts.map(productsItemName)).not.toContain('Home')
        const [popular] = navProductsTabLogic.values.groupedItems
        expect([popular.label, popular.items.map(productsItemName)]).toEqual([
            'Popular',
            [
                'Dashboards',
                'Product analytics',
                'Web analytics',
                'AI observability',
                'Session replay',
                'Replay vision',
                'Feature flags',
                'Experiments',
                'Error tracking',
                'Logs',
            ],
        ])
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setSearch('  self-driving  ')
        ).toMatchValues({
            pinnedItems: [expect.objectContaining({ href: urls.inbox(), path: 'Inbox', tags: ['beta'] })],
            groupedItems: [],
        })
        const items = [
            { path: 'Links', category: 'Unreleased', href: '/links' },
            { path: 'Web analytics', category: 'Analytics', href: '/web' },
            {
                path: 'LLM analytics',
                displayLabel: 'AI observability',
                category: 'AI engineering',
                href: '/ai',
                visualOrder: 1,
            },
            { path: 'AI gateway', category: 'AI engineering', href: '/ai-gateway' },
            { path: 'Logs', category: 'Monitoring', href: '/logs' },
        ]
        const groups = groupProducts(items, '')
        expect(groups.map((group) => [group.label, group.items.map(productsItemName)])).toEqual([
            ['Analytics', ['Web analytics']],
            ['AI engineering', ['AI gateway', 'AI observability']],
            ['Monitoring', ['Logs']],
            ['Unreleased', ['Links']],
        ])
        expect(groupProducts(items, 'observability')[0].items[0].href).toEqual('/ai')
    })

    it('lets all products close only when something is starred, and keeps it open after the first star', async () => {
        const starred = [{ id: 'star', path: 'Dashboards', type: 'dashboard', href: '/dashboard' }] as FileSystemEntry[]
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        navProductsTabLogic.actions.setAllProductsOpen(false)
        projectTreeDataLogic.actions.loadShortcutsSuccess(starred)
        expect(navProductsTabLogic.values).toMatchObject({ allProductsCollapsible: true, allProductsVisible: false })

        navProductsTabLogic.actions.setSearch('logs')
        expect(navProductsTabLogic.values.allProductsVisible).toBe(true)
        navProductsTabLogic.actions.setSearch('')

        navProductsTabLogic.actions.revealAllProductsForFind()
        expect(navProductsTabLogic.values).toMatchObject({ allProductsVisible: true, allProductsOpen: false })
        router.actions.push(urls.dashboards())
        expect(navProductsTabLogic.values.allProductsVisible).toBe(false)

        projectTreeDataLogic.actions.loadShortcutsSuccess([])
        expect(navProductsTabLogic.values).toMatchObject({ allProductsCollapsible: false, allProductsVisible: true })

        projectTreeDataLogic.actions.loadShortcutsSuccess(starred)
        expect(navProductsTabLogic.values).toMatchObject({ allProductsCollapsible: true, allProductsVisible: true })
    })

    it('fills in the link of product stars the backend created without one', async () => {
        const results = [
            { id: 'backend-star', path: 'Session replay', type: 'session_replay' },
            { id: 'folder', path: 'Research', type: 'folder', ref: 'Research' },
        ]
        useMocks({
            get: {
                '/api/environments/:team_id/file_system_shortcut/': { results },
                '/api/projects/:team_id/file_system_shortcut/': { results },
            },
        })
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        await expectLogic(projectTreeDataLogic, () =>
            projectTreeDataLogic.actions.loadShortcuts()
        ).toFinishAllListeners()
        expect(projectTreeDataLogic.values.shortcutData).toEqual([
            { id: 'backend-star', path: 'Session replay', type: 'session_replay', href: urls.replay() },
            { id: 'folder', path: 'Research', type: 'folder', ref: 'Research' },
        ])
    })

    it('filters starred products with the product search', async () => {
        const starredTree = projectTreeLogic({
            key: PRODUCTS_STARRED_TREE_KEY,
            root: 'shortcuts://',
            shortcutScope: 'products',
        })
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setSearch('onboarding')
        ).toDispatchActions([starredTree.actionTypes.setSearchTerm])
        expect(starredTree.values.searchTerm).toEqual('onboarding')
    })

    it('saves staged stars in one request without touching files, folders, or other shortcuts', async () => {
        const saved = [
            { id: 'folder', path: 'Feature flags', type: 'folder', ref: 'Feature flags' },
            { id: 'app-star', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' },
        ]
        const bulkUpdate = jest.fn(async ({ request }: { request: Request }) => {
            bulkUpdate.body = await request.json()
            return [200, saved]
        }) as jest.Mock & { body?: unknown }
        useMocks({ post: { '/api/projects/:team_id/file_system_shortcut/bulk_update/': bulkUpdate } })
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'folder', path: 'Feature flags', type: 'folder', ref: 'Feature flags' },
            { id: 'file', path: 'Feature flags', type: 'insight', ref: 'insight-1', href: '/insights/insight-1' },
            { id: 'analytics', path: 'Insights', type: 'product_analytics', href: '/insights' },
        ])

        navProductsTabLogic.actions.setAllProductsOpen(true)
        navProductsTabLogic.actions.setCustomizeSidebarOpen(true)
        navProductsTabLogic.actions.setDraftStarred('Product analytics', false)
        expect(navProductsTabLogic.values.allProductsOpen).toBe(true)
        navProductsTabLogic.actions.setDraftStarred('Feature flags', true)
        expect(navProductsTabLogic.values.allProductsOpen).toBe(false)
        expect(navProductsTabLogic.values.starredProductIds['Product analytics']).toBe('analytics')

        await expectLogic(navProductsTabLogic, () => navProductsTabLogic.actions.saveStarredProducts())
            .toDispatchActions(['saveStarredProductsSuccess'])
            .toMatchValues({ customizeSidebarOpen: false, starredProductsSaving: false })
        expect(bulkUpdate).toHaveBeenCalledTimes(1)
        expect(bulkUpdate.body).toEqual({
            add: [{ path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' }],
            remove_ids: ['analytics'],
        })
        expect(projectTreeDataLogic.values.shortcutData).toEqual(saved)
    })

    it.each([
        ['saves', 200, false, true],
        ['keeps the dialog and choices after a failed save', 500, true, false],
    ])('starred setup starts from custom products and %s', async (_name, status, staysOpen, completed) => {
        const bulkUpdate = jest.fn(() => [status, status === 200 ? [] : { detail: 'Try again' }])
        const updateUser = jest.fn(async ({ request }: { request: Request }) => {
            updateUser.body = await request.json()
            return [200, { ...MOCK_DEFAULT_USER, ...(updateUser.body as object) }]
        }) as jest.Mock & { body?: unknown }
        userLogic.mount()
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            ui_configuration: { version: 1, sidebar: { density: 'compact' } },
        })
        useMocks({
            post: { '/api/projects/:team_id/file_system_shortcut/bulk_update/': bulkUpdate },
            patch: { '/api/users/@me/': updateUser },
        })
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'analytics', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
        ])
        customProductsLogic.actions.loadCustomProductsSuccess([
            { id: '1', product_path: 'Session replay', enabled: true, created_at: '', updated_at: '' },
            { id: '2', product_path: 'Removed product', enabled: true, created_at: '', updated_at: '' },
        ])

        navProductsTabLogic.actions.openStarredSetup()
        expect([...navProductsTabLogic.values.draftStarredPaths].sort()).toEqual([
            'Product analytics',
            'Session replay',
        ])
        navProductsTabLogic.actions.setDraftStarred('Feature flags', true)
        navProductsTabLogic.actions.setAllProductsOpen(true)

        await expectLogic(navProductsTabLogic, () => navProductsTabLogic.actions.saveStarredProducts())
            .toDispatchActions([staysOpen ? 'saveStarredProductsFailure' : 'saveStarredProductsSuccess'])
            .toFinishAllListeners()
            .toMatchValues({ customizeSidebarOpen: staysOpen, starredProductsSaving: false })
        expect(updateUser).toHaveBeenCalledTimes(completed ? 1 : 0)
        expect(navProductsTabLogic.values.allProductsOpen).toBe(!completed)
        expect(updateUser.body).toEqual(
            completed
                ? {
                      ui_configuration: {
                          version: 1,
                          sidebar: { density: 'compact', starred_products_setup_completed: true },
                      },
                  }
                : undefined
        )
        expect(navProductsTabLogic.values.draftStarredPaths.has('Feature flags')).toBe(true)
        expect(customProductsLogic.values.customProducts).toHaveLength(2)
    })
    it('clean slate unstars every product, keeps folders, and completes setup in one save', async () => {
        const bulkUpdate = jest.fn(async ({ request }: { request: Request }) => {
            bulkUpdate.body = await request.json()
            return [200, [{ id: 'folder', path: 'Research', type: 'folder', ref: 'Research' }]]
        }) as jest.Mock & { body?: unknown }
        const updateUser = jest.fn(() => [200, MOCK_DEFAULT_USER])
        useMocks({
            post: { '/api/projects/:team_id/file_system_shortcut/bulk_update/': bulkUpdate },
            patch: { '/api/users/@me/': updateUser },
        })
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, ui_configuration: null })
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'folder', path: 'Research', type: 'folder', ref: 'Research' },
            { id: 'analytics', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
        ])
        customProductsLogic.actions.loadCustomProductsSuccess([
            { id: '1', product_path: 'Session replay', enabled: true, created_at: '', updated_at: '' },
        ])
        navProductsTabLogic.actions.openStarredSetup()

        await expectLogic(navProductsTabLogic, () => navProductsTabLogic.actions.startWithCleanSlate())
            .toDispatchActions(['saveStarredProductsSuccess'])
            .toFinishAllListeners()
            .toMatchValues({ customizeSidebarOpen: false })
        expect(bulkUpdate.body).toEqual({ add: [], remove_ids: ['analytics'] })
        expect(updateUser).toHaveBeenCalledTimes(1)
    })

    it('unselects every star, including preselected custom products, until the dialog reopens', async () => {
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'analytics', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
        ])
        customProductsLogic.actions.loadCustomProductsSuccess([
            { id: '1', product_path: 'Session replay', enabled: true, created_at: '', updated_at: '' },
        ])
        navProductsTabLogic.actions.openStarredSetup()

        navProductsTabLogic.actions.unselectAllStarred()
        navProductsTabLogic.actions.setDraftStarred('Logs', true)
        expect([...navProductsTabLogic.values.draftStarredPaths]).toEqual(['Logs'])

        navProductsTabLogic.actions.setCustomizeSidebarOpen(false)
        navProductsTabLogic.actions.openStarredSetup()
        expect([...navProductsTabLogic.values.draftStarredPaths].sort()).toEqual([
            'Product analytics',
            'Session replay',
        ])
    })

    it.each([
        ['products', ['Product analytics']],
        ['files', ['Overview', 'Research']],
        [undefined, ['Product analytics', 'Overview', 'Research']],
    ] as const)('keeps starred items in their own section: %s', (shortcutScope, expected) => {
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'product', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
            { id: 'file', path: 'Overview', type: 'dashboard', ref: '1', href: '/dashboard/1' },
            { id: 'folder', path: 'Research', type: 'folder', ref: 'Research' },
        ])
        const tree = projectTreeLogic({ key: `scoped-${shortcutScope}`, root: 'shortcuts://', shortcutScope })
        tree.mount()
        expect(tree.values.fullFileSystemFiltered.map((item) => item.name)).toEqual(expected)
        tree.actions.setSearchTerm('Product analytics')
        expect(tree.values.fullFileSystemFiltered.map((item) => item.name)).toEqual(
            shortcutScope === 'files' ? [] : ['Product analytics']
        )
    })
    it('closes the dialog and drops the unsaved draft when the project changes', () => {
        navProductsTabLogic.actions.setCustomizeSidebarOpen(true)
        navProductsTabLogic.actions.setDraftStarred('Feature flags', true)

        teamLogic.actions.loadCurrentTeamSuccess({
            ...teamLogic.values.currentTeam!,
            id: teamLogic.values.currentTeamId! + 1,
        })

        expect(navProductsTabLogic.values.customizeSidebarOpen).toBe(false)
        navProductsTabLogic.actions.setCustomizeSidebarOpen(true)
        expect(navProductsTabLogic.values.draftStarredPaths.has('Feature flags')).toBe(false)
    })

    it('splits the full ranked catalog at the threshold and clears the grouping', async () => {
        const requests: DecideRequestApi[] = []
        const decide = jest.fn(async ({ request }) => {
            const body: DecideRequestApi = await request.json()
            requests.push(body)
            return [
                200,
                {
                    model: 'test',
                    input_tokens: 1,
                    latency_ms: 1,
                    answers: Object.fromEntries(
                        Object.entries(body.questions).map(([key, question]: [string, { instructions: string }]) => [
                            key,
                            {
                                type: 'noul',
                                probability: question.instructions.includes('App: Web analytics.')
                                    ? 0.99
                                    : question.instructions.includes('App: SQL editor.')
                                      ? 0.5
                                      : question.instructions.includes('App: Feature flags.')
                                        ? 0.499
                                        : 0,
                            },
                        ])
                    ),
                },
            ]
        })
        useMocks({
            post: {
                '/api/projects/:team_id/ml_inference/decisions/decide/': decide,
            },
        })

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        const allApps = navProductsTabLogic.values.configurableProducts
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setAppRecommendationQuery('Track website visitors')
        ).toDispatchActions(['rankAppsSuccess'])
        expect(navProductsTabLogic.values.appRankingError).toBeNull()
        expect(navProductsTabLogic.values.rankedConfigurableApps[0].path).toBe('Web analytics')
        expect(new Set(navProductsTabLogic.values.rankedConfigurableApps)).toEqual(new Set(allApps))
        expect(decide.mock.calls.length).toBe(Math.ceil(allApps.length / 32))
        const questions = requests.flatMap(({ questions }) => Object.values(questions))
        expect(questions).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    instructions: expect.stringContaining('Find which referral sources bring visitors who sign up.'),
                }),
            ])
        )
        expect(navProductsTabLogic.values.appMatchGroups?.matching.map((item) => item.path)).toEqual([
            'Web analytics',
            'SQL editor',
        ])
        expect(navProductsTabLogic.values.appMatchGroups?.other.map((item) => item.path)).toContain('Feature flags')
        expect(navProductsTabLogic.values.customizeProductGroups[0]).toMatchObject({ label: SUGGESTED_GROUP_LABEL })
        expect(navProductsTabLogic.values.customizeProductGroups[0].items.map((item) => item.path)).toEqual([
            'Web analytics',
            'SQL editor',
        ])
        navProductsTabLogic.actions.openStarredSetup()
        expect(navProductsTabLogic.values.customizeProductGroups.map((group) => group.label)).not.toContain(
            SUGGESTED_GROUP_LABEL
        )
        expect(
            (navProductsTabLogic.values.appMatchGroups?.matching.length ?? 0) +
                (navProductsTabLogic.values.appMatchGroups?.other.length ?? 0)
        ).toBe(allApps.length)
        navProductsTabLogic.actions.setAppRecommendationQuery('Debug errors')
        expect(navProductsTabLogic.values.appRankings).toBeNull()
        expect(navProductsTabLogic.values.appMatchGroups).toBeNull()
        expect(navProductsTabLogic.values.rankedConfigurableApps).toEqual(allApps)
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setAppRecommendationQuery('')
        ).toDispatchActions(['rankAppsSuccess'])
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setAppRecommendationQuery('  Track website visitors  ')
        ).toDispatchActions(['rankAppsSuccess'])
        expect(decide.mock.calls.length).toBe(Math.ceil(allApps.length / 32))
        expect(navProductsTabLogic.values.appMatchGroups?.matching.map((item) => item.path)).toEqual([
            'Web analytics',
            'SQL editor',
        ])
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        expect(navProductsTabLogic.values.appRecommendationsEnabled).toBe(false)
        expect(navProductsTabLogic.values.rankedConfigurableApps).toEqual(allApps)
        expect(navProductsTabLogic.values.appMatchGroups).toBeNull()
        navProductsTabLogic.actions.setAppRecommendationQuery('')
        expect(navProductsTabLogic.values.rankedConfigurableApps).toEqual(allApps)
        expect(navProductsTabLogic.values.appMatchGroups).toBeNull()
    })

    it.each(['not approved', 'not loaded', 'revoked during debounce'])(
        'does not send app recommendations without consent, including debug mode: %s',
        async (consent) => {
            const decide = jest.fn(() => [503, { detail: 'Unavailable' }])
            useMocks({ post: { '/api/projects/:team_id/ml_inference/decisions/decide/': decide } })
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
            preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: true })
            await expectLogic(navProductsTabLogic, () => {
                if (consent === 'revoked during debounce') {
                    navProductsTabLogic.actions.setAppRecommendationQuery('Debug errors')
                }
                organizationLogic.actions.loadCurrentOrganizationSuccess(
                    consent === 'not loaded'
                        ? null
                        : { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false }
                )
                if (consent !== 'revoked during debounce') {
                    navProductsTabLogic.actions.setAppRecommendationQuery('Debug errors')
                }
            }).toFinishAllListeners()
            expect(decide).not.toHaveBeenCalled()
            expect(navProductsTabLogic.values.appRecommendationsEnabled).toBe(false)
            expect(navProductsTabLogic.values.appMatchGroups).toBeNull()
            expect(navProductsTabLogic.values.rankedConfigurableApps).toEqual(
                navProductsTabLogic.values.configurableProducts
            )
        }
    )

    it('leaves every app available when ranking fails and does not call Jev without enrollment', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: false })
        const decide = jest.fn(() => [503, { detail: 'Unavailable' }])
        useMocks({ post: { '/api/projects/:team_id/ml_inference/decisions/decide/': decide } })
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setAppRecommendationQuery('Debug errors')
        ).toDispatchActions(['rankAppsSuccess'])
        expect(decide).not.toHaveBeenCalled()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setAppRecommendationQuery('Debug errors')
        ).toDispatchActions(['rankAppsSuccess'])
        expect(decide).toHaveBeenCalled()
        expect(navProductsTabLogic.values.appRankingError).toEqual(expect.any(String))
        expect(navProductsTabLogic.values.rankedConfigurableApps).toEqual(
            navProductsTabLogic.values.configurableProducts
        )
        expect(navProductsTabLogic.values.appMatchGroups).toBeNull()
    })

    it('discards ranking responses after the query is cleared', async () => {
        let release!: () => void
        const held = new Promise<void>((resolve) => {
            release = resolve
        })
        const decide = jest.fn(async () => {
            await held
            return [200, { model: 'test', answers: { app_0: { type: 'noul', probability: 1 } }, input_tokens: 1 }]
        })
        useMocks({ post: { '/api/projects/:team_id/ml_inference/decisions/decide/': decide } })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        navProductsTabLogic.actions.setAppRecommendationQuery('Watch user sessions')
        await waitFor(() => expect(decide).toHaveBeenCalled())
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setAppRecommendationQuery('')
        ).toDispatchActions(['rankAppsSuccess'])
        release()
        await expectLogic(navProductsTabLogic).toFinishAllListeners()
        expect(navProductsTabLogic.values.appRankings).toBeNull()
        expect(navProductsTabLogic.values.appRankingError).toBeNull()
    })
})
