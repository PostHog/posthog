import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { DecideRequestApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { getDefaultTreeDataAndPeople, getDefaultTreeProducts } from '../../ProjectTree/defaultTree'
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
        const registry = [...getDefaultTreeProducts(), ...getDefaultTreeDataAndPeople()]
        const flags = Object.fromEntries(registry.flatMap((item) => (item.flag ? [[item.flag, enabled]] : [])))
        featureFlagLogic.actions.setFeatureFlags([], flags)
        const expected = new Set([
            urls.projectRoot(),
            urls.activity(ActivityTab.ExploreEvents),
            ...registry.filter((item) => item.href && (!item.flag || enabled)).map((item) => item.href),
            ...projectTreeDataLogic.values.groupItems
                .filter((item) => item.href && (!item.flag || flags[item.flag]))
                .map((item) => item.href),
        ])
        const actual = navProductsTabLogic.values.groupedItems.flatMap((group) => group.items.map((item) => item.href))
        expect(new Set(actual)).toEqual(expected)
        expect(actual).toHaveLength(expected.size)
    })

    it('searches display names and preserves person ordering alongside dynamic groups', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true })
        expect(navProductsTabLogic.values.groupedItems[0].items.map(productsItemName)).toEqual([
            'Home',
            'Self-driving',
            'Activity',
        ])
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setSearch('  self-driving  ')
        ).toMatchValues({
            groupedItems: [
                {
                    label: 'Project',
                    items: [expect.objectContaining({ href: urls.inbox(), path: 'Inbox', tags: ['beta'] })],
                },
            ],
        })
        const groups = groupProducts(
            [
                { path: 'Cohorts', category: 'People', href: '/cohorts', visualOrder: 20 },
                { path: 'Persons', category: 'People', href: '/persons', visualOrder: 10 },
                { path: 'group_0', displayLabel: 'Organizations', category: 'Groups', href: '/groups/0' },
            ],
            ''
        )
        expect(groups.find((group) => group.label === 'People')?.items.map(productsItemName)).toEqual([
            'Persons',
            'Cohorts',
        ])
        expect(
            groupProducts(
                groups.flatMap((group) => group.items),
                'organizations'
            )[0].items[0].href
        ).toEqual('/groups/0')
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
            { id: 'analytics', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
        ]
        projectTreeDataLogic.actions.loadShortcutsSuccess(existing)
        navProductsTabLogic.actions.setSearch('no matches')
        expect(navProductsTabLogic.values.starredProductIds['Feature flags']).toBeUndefined()

        await expectLogic(navProductsTabLogic, () => {
            navProductsTabLogic.actions.setProductStarred('Feature flags', true)
            navProductsTabLogic.actions.setProductStarred('Feature flags', true)
        }).toDispatchActions([navProductsTabLogic.actionTypes.saveAppStarsSuccess])
        expect(create).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual([...existing, app])
        expect(navProductsTabLogic.values.starredProductIds['Feature flags']).toBe('app-star')

        await expectLogic(navProductsTabLogic, () => {
            navProductsTabLogic.actions.setProductStarred('Feature flags', false)
            navProductsTabLogic.actions.setProductStarred('Feature flags', false)
        }).toDispatchActions([navProductsTabLogic.actionTypes.saveAppStarsSuccess])
        expect(remove).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual(existing)
    })

    it('keeps a star after a failed removal and allows a retry', async () => {
        const remove = jest
            .fn()
            .mockReturnValueOnce([500, { detail: 'Try again' }])
            .mockReturnValueOnce([204])
        useMocks({ delete: { '/api/projects/:team_id/file_system_shortcut/app-star/': remove } })
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'app-star', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' },
        ])

        await expectLogic(navProductsTabLogic, () => navProductsTabLogic.actions.setProductStarred('Feature flags', false))
            .toDispatchActions([navProductsTabLogic.actionTypes.saveAppStarsSuccess])
            .toMatchValues({
                starredProductIds: { 'Feature flags': 'app-star' },
                starSaveResultLoading: false,
                starSaveError: expect.any(String),
            })
        await expectLogic(navProductsTabLogic, () => navProductsTabLogic.actions.setProductStarred('Feature flags', false))
            .toDispatchActions([navProductsTabLogic.actionTypes.saveAppStarsSuccess])
            .toMatchValues({ starredProductIds: {}, starSaveResultLoading: false, starSaveError: null })
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
        navProductsTabLogic.actions.setConfigureStarredOpen(false)
        releaseCreate()
        await expectLogic(navProductsTabLogic).toDispatchActions(['saveAppStarsSuccess'])
        expect(create).toHaveBeenCalledTimes(1)
        expect(remove).toHaveBeenCalledTimes(2)
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
        expect(
            (navProductsTabLogic.values.appMatchGroups?.matching.length ?? 0) +
                (navProductsTabLogic.values.appMatchGroups?.other.length ?? 0)
        ).toBe(allApps.length)
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
            expect(navProductsTabLogic.values.rankedConfigurableApps).toEqual(navProductsTabLogic.values.configurableProducts)
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
        expect(navProductsTabLogic.values.rankedConfigurableApps).toEqual(navProductsTabLogic.values.configurableProducts)
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
