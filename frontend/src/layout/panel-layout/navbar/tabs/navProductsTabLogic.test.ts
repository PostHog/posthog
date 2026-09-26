import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

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
        navProductsTabLogic.actions.setSearch('no matches')
        expect(navProductsTabLogic.values.starredProductIds['Feature flags']).toBeUndefined()

        await expectLogic(navProductsTabLogic, () => {
            navProductsTabLogic.actions.setProductStarred('Feature flags', true)
            navProductsTabLogic.actions.setProductStarred('Feature flags', true)
        }).toDispatchActions([projectTreeDataLogic.actionTypes.addShortcutItemSuccess])
        expect(create).toHaveBeenCalledTimes(1)
        expect(projectTreeDataLogic.values.shortcutData).toEqual([...existing, app])
        expect(navProductsTabLogic.values.starredProductIds['Feature flags']).toBe('app-star')

        await expectLogic(navProductsTabLogic, () => {
            navProductsTabLogic.actions.setProductStarred('Feature flags', false)
            navProductsTabLogic.actions.setProductStarred('Feature flags', false)
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

        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setProductStarred('Feature flags', false)
        )
            .toDispatchActions([projectTreeDataLogic.actionTypes.deleteShortcutFailure])
            .toMatchValues({ starredProductIds: { 'Feature flags': 'app-star' }, shortcutDataLoading: false })
        await expectLogic(navProductsTabLogic, () =>
            navProductsTabLogic.actions.setProductStarred('Feature flags', false)
        )
            .toDispatchActions([projectTreeDataLogic.actionTypes.deleteShortcutSuccess])
            .toMatchValues({ starredProductIds: {}, shortcutDataLoading: false })
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
})
