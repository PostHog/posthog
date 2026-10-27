import { jumpBackObjectsForHome, recentObjectsForHome } from './todayRecentObjects'

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

    it.each([
        [
            ['d', 'e'],
            ['a', 'b', 'd', 'e', 'c'],
        ],
        [
            ['a', 'b', 'd', 'e'],
            ['a', 'b', 'd', 'e', 'c'],
        ],
        [['d'], ['a', 'b', 'd', 'c', 'e']],
        [[], ['a', 'b', 'c', 'd', 'e']],
        [
            ['d', 'd', 'e'],
            ['a', 'b', 'd', 'e', 'c'],
        ],
    ])('mixes recent and frequent items without duplicates (%j)', (frequentIds, expected) => {
        const entry = (id: string): { id: string; path: string; type: string; ref: string } => ({
            id,
            path: `Dashboards/${id}`,
            type: 'dashboard',
            ref: id,
        })
        expect(
            jumpBackObjectsForHome(['a', 'b', 'c', 'd', 'e'].map(entry), frequentIds.map(entry), 8).map(
                (item) => item.id
            )
        ).toEqual(expected)
    })
})
