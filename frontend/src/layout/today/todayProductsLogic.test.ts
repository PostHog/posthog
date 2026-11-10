import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { getNavProductItems } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { useMocks } from '~/mocks/jest'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ReplayTabs } from '~/types'

import { isPeopleListPath } from './todayPeople'
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

    it('lists every product of the current navigation but Home, People pane products included', () => {
        useMocks({ get: { '/api/projects/:team_id/file_system_shortcut/': { results: [] } } })
        initKeaTests()
        const flags = { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true, [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true }
        featureFlagLogic.actions.setFeatureFlags(Object.keys(flags), flags)
        const logic = todayProductsLogic()
        logic.mount()

        const hrefs = logic.values.products.map((item) => item.href)
        expect(hrefs).toEqual(
            getNavProductItems(flags)
                .map((item) => item.href)
                .filter((href) => href !== urls.projectRoot())
        )
        expect(hrefs).toEqual(
            expect.arrayContaining([
                urls.persons(),
                urls.customerAnalytics(),
                urls.supportTickets(),
                urls.replay(ReplayTabs.Home),
            ])
        )
    })

    // Cohorts and groups are not products in the Products pane, so the rule is tested on the paths.
    test.each([
        [urls.cohorts(), true],
        [urls.groups(0), true],
        ['/groups/0/new', true],
        [urls.supportTickets(), true],
        [urls.cohort(5), false],
        ['/groups/0/acme', false],
        ['/groups/0/acme/events', false],
    ])('isPeopleListPath(%s) is %s', (path, listed) => {
        expect(isPeopleListPath(path)).toBe(listed)
    })
})
