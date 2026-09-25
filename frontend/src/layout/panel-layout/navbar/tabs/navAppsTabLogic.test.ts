import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
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
import { appsItemName, groupApps } from './appsCatalog'
import { APPS_STARRED_TREE_KEY, navAppsTabLogic } from './navAppsTabLogic'

describe('navAppsTabLogic', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/file_system_shortcut/': { results: [] } } })
        initKeaTests()
        navAppsTabLogic.mount()
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
        const actual = navAppsTabLogic.values.groupedItems.flatMap((group) => group.items.map((item) => item.href))
        expect(new Set(actual)).toEqual(expected)
        expect(actual).toHaveLength(expected.size)
    })

    it('searches display names and preserves person ordering alongside dynamic groups', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true })
        expect(navAppsTabLogic.values.groupedItems[0].items.map(appsItemName)).toEqual([
            'Home',
            'Self-driving',
            'Activity',
        ])
        await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setSearch('  self-driving  ')).toMatchValues({
            groupedItems: [
                {
                    label: 'Project',
                    items: [expect.objectContaining({ href: urls.inbox(), path: 'Inbox', tags: ['beta'] })],
                },
            ],
        })
        const groups = groupApps(
            [
                { path: 'Cohorts', category: 'People', href: '/cohorts', visualOrder: 20 },
                { path: 'Persons', category: 'People', href: '/persons', visualOrder: 10 },
                { path: 'group_0', displayLabel: 'Organizations', category: 'Groups', href: '/groups/0' },
            ],
            ''
        )
        expect(groups.find((group) => group.label === 'People')?.items.map(appsItemName)).toEqual([
            'Persons',
            'Cohorts',
        ])
        expect(
            groupApps(
                groups.flatMap((group) => group.items),
                'organizations'
            )[0].items[0].href
        ).toEqual('/groups/0')
    })

    it('filters starred apps with the app search', async () => {
        const starredTree = projectTreeLogic({
            key: APPS_STARRED_TREE_KEY,
            root: 'shortcuts://',
            shortcutScope: 'apps',
        })
        await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setSearch('onboarding')).toDispatchActions([
            starredTree.actionTypes.setSearchTerm,
        ])
        expect(starredTree.values.searchTerm).toEqual('onboarding')
    })

    it('configures app stars without changing files, folders, or existing order', async () => {
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
        navAppsTabLogic.actions.setSearch('no matches')
        expect(navAppsTabLogic.values.starredAppIds['Feature flags']).toBeUndefined()

        await expectLogic(navAppsTabLogic, () => {
            navAppsTabLogic.actions.setAppStarred('Feature flags', true)
            navAppsTabLogic.actions.setAppStarred('Feature flags', true)
        }).toDispatchActions([navAppsTabLogic.actionTypes.saveAppStarsSuccess])
        expect(create).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual([...existing, app])
        expect(navAppsTabLogic.values.starredAppIds['Feature flags']).toBe('app-star')

        await expectLogic(navAppsTabLogic, () => {
            navAppsTabLogic.actions.setAppStarred('Feature flags', false)
            navAppsTabLogic.actions.setAppStarred('Feature flags', false)
        }).toDispatchActions([navAppsTabLogic.actionTypes.saveAppStarsSuccess])
        expect(remove).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual(existing)
    })

    it.each(['before', 'after'])(
        'reports a failed removal when the modal closes %s the failure and allows a retry',
        async (closed) => {
            const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue('save-error')
            navAppsTabLogic.actions.setConfigureStarredOpen(true)
            const remove = jest
                .fn()
                .mockReturnValueOnce([500, { detail: 'Try again' }])
                .mockReturnValueOnce([204])
            useMocks({ delete: { '/api/projects/:team_id/file_system_shortcut/app-star/': remove } })
            await expectLogic(projectTreeDataLogic).toFinishAllListeners()
            projectTreeDataLogic.actions.loadShortcutsSuccess([
                { id: 'app-star', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' },
            ])

            await expectLogic(navAppsTabLogic, () => {
                navAppsTabLogic.actions.setAppStarred('Feature flags', false)
                if (closed === 'before') {
                    navAppsTabLogic.actions.setConfigureStarredOpen(false)
                }
            })
                .toDispatchActions([navAppsTabLogic.actionTypes.saveAppStarsSuccess])
                .toMatchValues({
                    starredAppIds: { 'Feature flags': 'app-star' },
                    starSaveResultLoading: false,
                    starSaveError: expect.any(String),
                })
            if (closed === 'after') {
                expect(errorToast).not.toHaveBeenCalled()
                navAppsTabLogic.actions.setConfigureStarredOpen(false)
            }
            expect(errorToast).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({
                    toastId: 'configure-starred-save-error',
                    autoClose: false,
                    button: { label: 'Configure starred', action: expect.any(Function) },
                })
            )
            errorToast.mock.calls[0][1]?.button?.action()
            expect(navAppsTabLogic.values.configureStarredOpen).toBe(true)
            await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setAppStarred('Feature flags', false))
                .toDispatchActions([navAppsTabLogic.actionTypes.saveAppStarsSuccess])
                .toMatchValues({ starredAppIds: {}, starSaveResultLoading: false, starSaveError: null })
            errorToast.mockRestore()
        }
    )
    it.each([
        ['apps', ['Product analytics']],
        ['files', ['Overview', 'Research']],
        [undefined, ['Product analytics', 'Overview', 'Research']],
    ] as const)('keeps starred items in their own section: %s', (shortcutScope, expected) => {
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'app', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
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
        navAppsTabLogic.actions.setAppStarred('Feature flags', true)
        await expectLogic(navAppsTabLogic).toDispatchActions(['saveAppStars'])
        expect(navAppsTabLogic.values.selectedAppStars['Feature flags']).toBe(true)
        navAppsTabLogic.actions.setAppStarred('Product analytics', false)
        navAppsTabLogic.actions.setAppStarred('Feature flags', false)
        expect(navAppsTabLogic.values.selectedAppStars).toMatchObject({
            'Feature flags': false,
            'Product analytics': false,
        })
        navAppsTabLogic.actions.setConfigureStarredOpen(false)
        releaseCreate()
        await expectLogic(navAppsTabLogic).toDispatchActions(['saveAppStarsSuccess'])
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
        const allApps = navAppsTabLogic.values.configurableApps
        await expectLogic(navAppsTabLogic, () =>
            navAppsTabLogic.actions.setAppRecommendationQuery('Track website visitors')
        ).toDispatchActions(['rankAppsSuccess'])
        expect(navAppsTabLogic.values.appRankingError).toBeNull()
        expect(navAppsTabLogic.values.rankedConfigurableApps[0].path).toBe('Web analytics')
        expect(new Set(navAppsTabLogic.values.rankedConfigurableApps)).toEqual(new Set(allApps))
        expect(decide.mock.calls.length).toBe(Math.ceil(allApps.length / 32))
        const questions = requests.flatMap(({ questions }) => Object.values(questions))
        expect(questions).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    instructions: expect.stringContaining('Find which referral sources bring visitors who sign up.'),
                }),
            ])
        )
        expect(navAppsTabLogic.values.appMatchGroups?.matching.map((item) => item.path)).toEqual([
            'Web analytics',
            'SQL editor',
        ])
        expect(navAppsTabLogic.values.appMatchGroups?.other.map((item) => item.path)).toContain('Feature flags')
        expect(
            (navAppsTabLogic.values.appMatchGroups?.matching.length ?? 0) +
                (navAppsTabLogic.values.appMatchGroups?.other.length ?? 0)
        ).toBe(allApps.length)
        await expectLogic(navAppsTabLogic, () =>
            navAppsTabLogic.actions.setAppRecommendationQuery('')
        ).toDispatchActions(['rankAppsSuccess'])
        await expectLogic(navAppsTabLogic, () =>
            navAppsTabLogic.actions.setAppRecommendationQuery('  Track website visitors  ')
        ).toDispatchActions(['rankAppsSuccess'])
        expect(decide.mock.calls.length).toBe(Math.ceil(allApps.length / 32))
        expect(navAppsTabLogic.values.appMatchGroups?.matching.map((item) => item.path)).toEqual([
            'Web analytics',
            'SQL editor',
        ])
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        expect(navAppsTabLogic.values.appRecommendationsEnabled).toBe(false)
        expect(navAppsTabLogic.values.rankedConfigurableApps).toEqual(allApps)
        expect(navAppsTabLogic.values.appMatchGroups).toBeNull()
        navAppsTabLogic.actions.setAppRecommendationQuery('')
        expect(navAppsTabLogic.values.rankedConfigurableApps).toEqual(allApps)
        expect(navAppsTabLogic.values.appMatchGroups).toBeNull()
    })

    it.each(['not approved', 'not loaded', 'revoked during debounce'])(
        'does not send app recommendations without consent, including debug mode: %s',
        async (consent) => {
            const decide = jest.fn(() => [503, { detail: 'Unavailable' }])
            useMocks({ post: { '/api/projects/:team_id/ml_inference/decisions/decide/': decide } })
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
            preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: true })
            await expectLogic(navAppsTabLogic, () => {
                if (consent === 'revoked during debounce') {
                    navAppsTabLogic.actions.setAppRecommendationQuery('Debug errors')
                }
                organizationLogic.actions.loadCurrentOrganizationSuccess(
                    consent === 'not loaded'
                        ? null
                        : { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false }
                )
                if (consent !== 'revoked during debounce') {
                    navAppsTabLogic.actions.setAppRecommendationQuery('Debug errors')
                }
            }).toFinishAllListeners()
            expect(decide).not.toHaveBeenCalled()
            expect(navAppsTabLogic.values.appRecommendationsEnabled).toBe(false)
            expect(navAppsTabLogic.values.appMatchGroups).toBeNull()
            expect(navAppsTabLogic.values.rankedConfigurableApps).toEqual(navAppsTabLogic.values.configurableApps)
        }
    )

    it('leaves every app available when ranking fails and does not call Jev without enrollment', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: false })
        const decide = jest.fn(() => [503, { detail: 'Unavailable' }])
        useMocks({ post: { '/api/projects/:team_id/ml_inference/decisions/decide/': decide } })
        await expectLogic(navAppsTabLogic, () =>
            navAppsTabLogic.actions.setAppRecommendationQuery('Debug errors')
        ).toDispatchActions(['rankAppsSuccess'])
        expect(decide).not.toHaveBeenCalled()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        await expectLogic(navAppsTabLogic, () =>
            navAppsTabLogic.actions.setAppRecommendationQuery('Debug errors')
        ).toDispatchActions(['rankAppsSuccess'])
        expect(decide).toHaveBeenCalled()
        expect(navAppsTabLogic.values.appRankingError).toEqual(expect.any(String))
        expect(navAppsTabLogic.values.rankedConfigurableApps).toEqual(navAppsTabLogic.values.configurableApps)
        expect(navAppsTabLogic.values.appMatchGroups).toBeNull()
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
        navAppsTabLogic.actions.setAppRecommendationQuery('Watch user sessions')
        await waitFor(() => expect(decide).toHaveBeenCalled())
        await expectLogic(navAppsTabLogic, () =>
            navAppsTabLogic.actions.setAppRecommendationQuery('')
        ).toDispatchActions(['rankAppsSuccess'])
        release()
        await expectLogic(navAppsTabLogic).toFinishAllListeners()
        expect(navAppsTabLogic.values.appRankings).toBeNull()
        expect(navAppsTabLogic.values.appRankingError).toBeNull()
    })
})
