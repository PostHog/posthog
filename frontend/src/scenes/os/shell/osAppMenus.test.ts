import { routes } from 'scenes/scenes'

import { getTreeItemsProducts } from '~/products'

import { OS_SYSTEM_APPS, osCatalogApps } from '../store/osAppCatalog'
import { OS_APP_MENU_PAGES, osAppMenuFor } from './osAppMenus'

const allFlagsOn = new Proxy({}, { get: () => true }) as Record<string, boolean>
const flagsOff = new Proxy({}, { get: () => false }) as Record<string, boolean>
const apps = [...OS_SYSTEM_APPS, ...osCatalogApps(getTreeItemsProducts(), allFlagsOn)]

// kea-router patterns: `:name` is one segment, `*` is the rest, `(...)` is optional.
function routeRegex(pattern: string): RegExp {
    const source = pattern
        .replace(/[.+?^${}|[\]\\]/g, '\\$&')
        .replace(/\(/g, '(?:')
        .replace(/\)/g, ')?')
        .replace(/:[a-zA-Z_]+/g, '[^/]+')
        .replace(/\*/g, '.*')
    return new RegExp(`^${source}/?$`)
}
const routeRegexes = Object.keys(routes).map(routeRegex)

describe('osAppMenuFor', () => {
    it.each([
        {
            path: '/project/1/insights?tab=history',
            app: 'Product analytics',
            active: 'History',
        },
        { path: '/project/1/insights', app: 'Product analytics', active: 'Home' },
        { path: '/project/1/insights?tab=all', app: 'Product analytics', active: 'All insights' },
        { path: '/project/1/alerts', app: 'Product analytics', active: 'Alerts' },
        { path: '/project/1/insights/abc123/edit', app: 'Product analytics', active: null },
        { path: '/project/1/replay/playlists', app: 'Session replay', active: 'Collections' },
        { path: '/project/1/replay/abc?t=10', app: 'Session replay', active: null },
        { path: '/project/1/web/web-vitals', app: 'Web analytics', active: 'Web vitals' },
        { path: '/project/1/feature_flags?tab=history', app: 'Feature flags', active: 'History' },
        { path: '/project/1/activity/live', app: 'Activity', active: 'Live' },
        { path: '/project/1/settings/organization', app: 'Settings', active: 'Organization' },
    ])('resolves $path to $app with $active active', ({ path, app, active }) => {
        const menu = osAppMenuFor(path, apps, allFlagsOn)
        expect(menu?.app.name).toEqual(app)
        expect(menu?.activePage?.label ?? null).toEqual(active)
    })

    it.each([
        ['on', allFlagsOn, 'Home'],
        ['off', flagsOff, 'All insights'],
    ])('marks the tab the app opens on when the home tab flag is %s', (_, flags, active) => {
        expect(osAppMenuFor('/project/1/insights', apps, flags)?.activePage?.label).toEqual(active)
    })

    it('lists the app pages in menu order, and links related apps separately', () => {
        const menu = osAppMenuFor('/project/1/insights', apps, allFlagsOn)
        expect(menu?.pages.map((page) => page.label)).toEqual([
            'Home',
            'All insights',
            'My insights',
            'Alerts',
            'Notifications',
            'History',
        ])
        expect(menu?.relatedApps.map((page) => [page.label, page.href])).toEqual([['Dashboards', '/dashboard']])
    })

    it('gives an app without its own pages a menu with its home page and its "new" items', () => {
        const menu = osAppMenuFor('/project/1/dashboard/12', apps, allFlagsOn)
        expect(menu?.app.name).toEqual('Dashboards')
        expect(menu?.pages).toEqual([{ label: 'Dashboards', href: '/dashboard' }])
        expect(menu?.activePage).toBeNull()
        expect(menu?.newItems.map((item) => item.label)).toContain('Dashboard')
    })

    it('lists the "new" items of an app from the product manifests, and only the ones that stay in the app', () => {
        const menu = osAppMenuFor('/project/1/insights', apps, allFlagsOn)
        expect(menu?.newItems.map((item) => item.label)).toEqual(
            expect.arrayContaining(['Trends', 'Funnel', 'Retention'])
        )
        expect(menu?.newItems.map((item) => osAppMenuFor(item.href, apps, allFlagsOn)?.app.key)).toEqual(
            menu?.newItems.map(() => 'Product analytics')
        )
    })

    it('hides "new" items behind a feature flag that is off', () => {
        const labels = osAppMenuFor('/project/1/insights', apps, flagsOff)?.newItems.map((item) => item.label)
        expect(labels).toContain('Trends')
        expect(labels).not.toContain('Journeys')
    })

    it.each([
        ['a page no app claims', '/project/1/person/abc'],
        ['the desktop with no path', null],
    ])('returns no menu for %s', (_, path) => {
        expect(osAppMenuFor(path, apps, allFlagsOn)).toBeNull()
    })

    it('does not claim pages for an app the user cannot see', () => {
        const withoutProductAnalytics = apps.filter((app) => app.key !== 'Product analytics')
        expect(osAppMenuFor('/project/1/alerts', withoutProductAnalytics, allFlagsOn)).toBeNull()
    })

    it('only lists pages that are real routes and that open in the same app', () => {
        for (const [appKey, menuPages] of Object.entries(OS_APP_MENU_PAGES)) {
            expect(apps.some((app) => app.key === appKey)).toBe(true)
            for (const page of menuPages) {
                const pathname = page.href.split(/[?#]/)[0]
                expect([page.label, routeRegexes.some((regex) => regex.test(pathname))]).toEqual([page.label, true])
                expect([page.label, osAppMenuFor(page.href, apps, allFlagsOn)?.app.key]).toEqual([page.label, appKey])
            }
        }
    })
})
