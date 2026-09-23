import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { getDefaultTreeDataAndPeople, getDefaultTreeProducts } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { appsItemName, groupApps } from './appsCatalog'
import { APPS_STARRED_TREE_KEY, navAppsTabLogic } from './navAppsTabLogic'

describe('navAppsTabLogic', () => {
    beforeEach(() => {
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
