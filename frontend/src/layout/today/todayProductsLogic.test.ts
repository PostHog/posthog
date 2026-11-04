import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { getNavProductItems } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { useMocks } from '~/mocks/jest'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ReplayTabs } from '~/types'

import { resolveStarredProducts, todayProductsLogic } from './todayProductsLogic'

const productShortcut = (id: string, path: string, href?: string): FileSystemEntry =>
    ({ id, path, type: 'product', href }) as FileSystemEntry

describe('todayProductsLogic', () => {
    it('resolves product stars in saved order, by name or by link', () => {
        const candidates: FileSystemImport[] = getNavProductItems({})
        const shortcuts = [
            productShortcut('1', 'Session replay'),
            // Stars made by the backend have no href, so they match by name.
            productShortcut('2', 'Product analytics'),
            { id: '3', path: 'Weekly signups', type: 'insight', ref: 'abc', href: '/insights/abc' } as FileSystemEntry,
            productShortcut('4', 'Old name', '/replay/home'),
            productShortcut('5', 'Not a product'),
        ]

        expect(resolveStarredProducts(shortcuts, candidates).map((item) => item.path)).toEqual([
            'Session replay',
            'Product analytics',
        ])
    })

    test.each([
        ['with the People pane', { [FEATURE_FLAGS.TODAY_RAIL_PEOPLE]: true }, false],
        ['without the People pane', {}, true],
    ])('%s, the Products pane lists Persons and Customer analytics: %s', (_, extraFlags, listed) => {
        useMocks({ get: { '/api/projects/:team_id/file_system_shortcut/': { results: [] } } })
        initKeaTests()
        const flags = {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true,
            ...extraFlags,
        }
        featureFlagLogic.actions.setFeatureFlags(Object.keys(flags), flags)
        const logic = todayProductsLogic()
        logic.mount()

        const hrefs = logic.values.products.map((item) => item.href)
        expect(hrefs.includes(urls.persons())).toBe(listed)
        expect(hrefs.includes(urls.customerAnalytics())).toBe(listed)
        expect(hrefs).toContain(urls.replay(ReplayTabs.Home))
    })
})
