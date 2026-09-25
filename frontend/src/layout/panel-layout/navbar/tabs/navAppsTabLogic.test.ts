import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

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
            post: { '/api/environments/:team_id/file_system_shortcut/': create },
            delete: { '/api/environments/:team_id/file_system_shortcut/app-star/': remove },
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
        }).toDispatchActions([projectTreeDataLogic.actionTypes.addShortcutItemSuccess])
        expect(create).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual([...existing, app])
        expect(navAppsTabLogic.values.starredAppIds['Feature flags']).toBe('app-star')

        await expectLogic(navAppsTabLogic, () => {
            navAppsTabLogic.actions.setAppStarred('Feature flags', false)
            navAppsTabLogic.actions.setAppStarred('Feature flags', false)
        }).toDispatchActions([projectTreeDataLogic.actionTypes.deleteShortcutSuccess])
        expect(remove).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual(existing)
    })

    it('keeps a star after a failed removal and allows a retry', async () => {
        const remove = jest
            .fn()
            .mockReturnValueOnce([500, { detail: 'Try again' }])
            .mockReturnValueOnce([204])
        useMocks({ delete: { '/api/environments/:team_id/file_system_shortcut/app-star/': remove } })
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'app-star', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' },
        ])

        await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setAppStarred('Feature flags', false))
            .toDispatchActions([projectTreeDataLogic.actionTypes.deleteShortcutFailure])
            .toMatchValues({ starredAppIds: { 'Feature flags': 'app-star' }, shortcutDataLoading: false })
        await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setAppStarred('Feature flags', false))
            .toDispatchActions([projectTreeDataLogic.actionTypes.deleteShortcutSuccess])
            .toMatchValues({ starredAppIds: {}, shortcutDataLoading: false })
    })
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
})
