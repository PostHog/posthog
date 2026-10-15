import { recentObjectsForHome } from './todayRecentObjects'

describe('recentObjectsForHome', () => {
    it('keeps agent sessions and entries with no page out of the recent objects', () => {
        const recents = [
            { id: 'task', path: 'Tasks/Fix the flaky test', type: 'task', href: '/tasks/1' },
            { id: 'dashboard', path: 'Dashboards/Growth', type: 'dashboard', href: '/dashboard/1' },
            { id: 'unlinked', path: 'Insights/Draft', type: 'insight' },
            { id: 'by-ref', path: 'Flags/checkout', type: 'feature_flag', ref: '7' },
            { id: 'insight', path: 'Insights/Funnel', type: 'insight/funnels', href: '/insights/a' },
        ]

        expect(recentObjectsForHome(recents, 3).map((entry) => entry.id)).toEqual(['dashboard', 'by-ref', 'insight'])
    })
})
