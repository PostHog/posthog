import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { DecideRequestApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { getDefaultTreeData, getDefaultTreeProducts } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { PRODUCTS_STARRED_TREE_KEY, navProductsTabLogic } from './navProductsTabLogic'
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
            urls.persons(),
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
            'Activity',
            'People and groups',
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

        projectTreeDataLogic.actions.loadShortcutsSuccess([])
        expect(navProductsTabLogic.values).toMatchObject({ allProductsCollapsible: false, allProductsVisible: true })

        projectTreeDataLogic.actions.loadShortcutsSuccess(starred)
        expect(navProductsTabLogic.values).toMatchObject({ allProductsCollapsible: true, allProductsVisible: true })
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

    it('configures product stars without changing files, folders, or existing order', async () => {
        const app = { id: 'app-star', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' }
        const create = jest.fn(() => [201, app])
        const remove = jest.fn(() => [204])
        useMocks({
            post: { '/api/projects/:team_id/file_system_shortcut/': create },
            delete: { '/api/projects/:team_id/file_system_shortcut/app-star/': remove },
        })
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        const existing = [
            { id: 'folder', path: 'Feature flags', type: 'folder', ref: 'Feature flags' },
            { id: 'file', path: 'Feature flags', type: 'insight', ref: 'insight-1', href: '/insights/insight-1' },
            { id: 'analytics', path: 'Insights', type: 'product_analytics', href: '/insights' },
        ]
        projectTreeDataLogic.actions.loadShortcutsSuccess(existing)
        navProductsTabLogic.actions.setSearch('no matches')
        expect(navProductsTabLogic.values.starredProductIds['Feature flags']).toBeUndefined()
        expect(navProductsTabLogic.values.starredProductIds['Product analytics']).toBe('analytics')

        await expectLogic(navProductsTabLogic, () => {
            navProductsTabLogic.actions.setProductStarred('Feature flags', true)
            navProductsTabLogic.actions.setProductStarred('Feature flags', true)
        }).toDispatchActions([navProductsTabLogic.actionTypes.saveAppStarsSuccess])
        expect(create).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual([...existing, app])
        expect(navProductsTabLogic.values.starredProductIds['Feature flags']).toBe('app-star')
        expect(navProductsTabLogic.values.starSaveError).toBeNull()
        expect(posthog.capture).toHaveBeenCalledWith('navbar starred item added', {
            item_type: 'feature_flag',
            item_name: 'Feature flags',
        })

        await expectLogic(navProductsTabLogic, () => {
            navProductsTabLogic.actions.setProductStarred('Feature flags', false)
            navProductsTabLogic.actions.setProductStarred('Feature flags', false)
        }).toDispatchActions([navProductsTabLogic.actionTypes.saveAppStarsSuccess])
        expect(remove).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual(existing)
        expect(navProductsTabLogic.values.starSaveError).toBeNull()
        expect(posthog.capture).toHaveBeenCalledWith('navbar starred item removed', {
            item_type: 'feature_flag',
            item_name: 'Feature flags',
        })
    })

    it.each(['before', 'after'])(
        'reports a failed removal when the modal closes %s the failure and allows a retry',
        async (closed) => {
            const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('save-error')
            navProductsTabLogic.actions.setCustomizeSidebarOpen(true)
            const remove = jest
                .fn()
                .mockReturnValueOnce([500, { detail: 'Try again' }])
                .mockReturnValueOnce([204])
            useMocks({ delete: { '/api/projects/:team_id/file_system_shortcut/app-star/': remove } })
            await expectLogic(projectTreeDataLogic).toFinishAllListeners()
            projectTreeDataLogic.actions.loadShortcutsSuccess([
                { id: 'app-star', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' },
            ])

            await expectLogic(navProductsTabLogic, () => {
                navProductsTabLogic.actions.setProductStarred('Feature flags', false)
                if (closed === 'before') {
                    navProductsTabLogic.actions.setCustomizeSidebarOpen(false)
                }
            })
                .toDispatchActions([navProductsTabLogic.actionTypes.saveAppStarsSuccess])
                .toMatchValues({
                    starredProductIds: { 'Feature flags': 'app-star' },
                    starSaveResultLoading: false,
                    starSaveError: expect.any(String),
                })
            if (closed === 'after') {
                expect(errorToast).not.toHaveBeenCalled()
                navProductsTabLogic.actions.setCustomizeSidebarOpen(false)
            }
            expect(errorToast).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    toastId: 'configure-starred-save-error',
                    autoClose: false,
                    button: { label: 'Customize sidebar', action: expect.any(Function) },
                })
            )
            errorToast.mock.calls[0][1]?.button?.action()
            expect(navProductsTabLogic.values.customizeSidebarOpen).toBe(true)
            await expectLogic(navProductsTabLogic, () =>
                navProductsTabLogic.actions.setProductStarred('Feature flags', false)
            )
                .toDispatchActions([navProductsTabLogic.actionTypes.saveAppStarsSuccess])
                .toMatchValues({ starredProductIds: {}, starSaveResultLoading: false, starSaveError: null })
            errorToast.mockRestore()
        }
    )
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
    it('keeps edits responsive while saving, preserves the latest intent, and finishes after the modal closes', async () => {
        let releaseCreate!: () => void
        const held = new Promise<void>((resolve) => {
            releaseCreate = resolve
        })
        const create = jest.fn(async () => {
            await held
            return [201, { id: 'new-star', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' }]
        })
        const remove = jest.fn(() => [204])
        useMocks({
            post: { '/api/projects/:team_id/file_system_shortcut/': create },
            delete: { '/api/projects/:team_id/file_system_shortcut/:id/': remove },
        })
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'analytics', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
        ])
        navProductsTabLogic.actions.setProductStarred('Feature flags', true)
        await expectLogic(navProductsTabLogic).toDispatchActions(['saveAppStars'])
        expect(navProductsTabLogic.values.selectedAppStars['Feature flags']).toBe(true)
        navProductsTabLogic.actions.setProductStarred('Product analytics', false)
        navProductsTabLogic.actions.setProductStarred('Feature flags', false)
        expect(navProductsTabLogic.values.selectedAppStars).toMatchObject({
            'Feature flags': false,
            'Product analytics': false,
        })
        navProductsTabLogic.actions.setCustomizeSidebarOpen(false)
        releaseCreate()
        await expectLogic(navProductsTabLogic).toDispatchActions(['saveAppStarsSuccess'])
        expect(create).toHaveBeenCalledTimes(1)
        expect(remove).toHaveBeenCalledTimes(2)
    })

    it.each([201, 500])(
        'isolates queued saves when the project changes during a request returning %s',
        async (status) => {
            let release!: () => void
            const held = new Promise<void>((resolve) => {
                release = resolve
            })
            const oldTeamId = teamLogic.values.currentTeamId!
            const newTeamId = oldTeamId + 1
            const create = jest.fn(async ({ request }) => {
                const oldProject = new URL(request.url).pathname.includes(`/projects/${oldTeamId}/`)
                if (oldProject) {
                    await held
                }
                return [
                    oldProject ? status : 201,
                    {
                        id: oldProject ? 'old-project-star' : 'new-project-star',
                        path: 'Feature flags',
                        type: 'feature_flag',
                        href: '/feature_flags',
                    },
                ]
            })
            const remove = jest.fn(() => [204])
            const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('project-change')
            useMocks({
                post: { '/api/projects/:team_id/file_system_shortcut/': create },
                delete: { '/api/projects/:team_id/file_system_shortcut/:id/': remove },
            })
            await expectLogic(projectTreeDataLogic).toFinishAllListeners()
            projectTreeDataLogic.actions.loadShortcutsSuccess([
                { id: 'old-analytics', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
            ])
            navProductsTabLogic.actions.setProductStarred('Feature flags', true)
            await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
            navProductsTabLogic.actions.setProductStarred('Product analytics', false)
            teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, id: newTeamId })
            projectTreeDataLogic.actions.loadShortcutsSuccess([])
            expect(navProductsTabLogic.values.pendingAppStars).toEqual({})
            await expectLogic(navProductsTabLogic, () =>
                navProductsTabLogic.actions.setProductStarred('Feature flags', true)
            ).toDispatchActions(['saveAppStarsSuccess'])
            release()
            await expectLogic(navProductsTabLogic).toFinishAllListeners()
            expect(create).toHaveBeenCalledTimes(2)
            expect(remove).not.toHaveBeenCalled()
            expect(projectTreeDataLogic.values.shortcutData.map(({ id }) => id)).toEqual(['new-project-star'])
            expect(navProductsTabLogic.values.starSaveError).toBeNull()
            expect(errorToast).toHaveBeenCalledTimes(1)
            errorToast.mockRestore()
        }
    )

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
