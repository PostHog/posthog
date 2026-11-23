import { jumpBackObjectsForHome, recentObjectsForHome } from './todayRecentObjects'

describe('recentObjectsForHome', () => {
    it('keeps agent sessions and entries with no page out of the recent objects', () => {
        const recents = [
            { id: 'task', path: 'Tasks/Fix the flaky test', type: 'task', href: '/tasks/1' },
            { id: 'dashboard', path: 'Dashboards/Growth', type: 'dashboard', href: '/dashboard/1' },
            { id: 'dashboard-copy', path: 'Pinned/Growth', type: 'dashboard', ref: '1' },
            { id: 'unlinked', path: 'Insights/Draft', type: 'insight' },
            { id: 'by-ref', path: 'Flags/checkout', type: 'feature_flag', ref: '7' },
            { id: 'insight', path: 'Insights/Funnel', type: 'insight/funnels', href: '/insights/a' },
            { id: 'insight-copy', path: 'Pinned/Funnel', type: 'insight', ref: 'a' },
            { id: 'query-one', path: 'Queries/One', href: '/sql?open_saved_query=one' },
            { id: 'query-two', path: 'Queries/Two', href: '/sql?open_saved_query=two' },
        ]

        expect(recentObjectsForHome(recents, 5).map((entry) => entry.id)).toEqual([
            'dashboard',
            'by-ref',
            'insight',
            'query-one',
            'query-two',
        ])
    })

    it.each([
        [
            ['a', 'b', 'c', 'd', 'e'],
            ['d', 'e'],
            ['a', 'b', 'd', 'e', 'c'],
        ],
        [
            ['a', 'b', 'c', 'd', 'e'],
            ['a', 'b', 'd', 'e'],
            ['a', 'b', 'd', 'e', 'c'],
        ],
        [['a', 'b', 'c', 'd', 'e'], ['d'], ['a', 'b', 'd', 'c', 'e']],
        [['a', 'b', 'c', 'd', 'e'], [], ['a', 'b', 'c', 'd', 'e']],
        [
            ['a', 'b', 'c', 'd', 'e'],
            ['d', 'd', 'e'],
            ['a', 'b', 'd', 'e', 'c'],
        ],
        [
            ['a', 'a', 'b', 'c', 'd', 'e'],
            ['c', 'd'],
            ['a', 'b', 'c', 'd', 'e'],
        ],
        [
            ['a', 'b', 'c', 'c', 'd', 'e'],
            ['d', 'e'],
            ['a', 'b', 'd', 'e', 'c'],
        ],
        [['a', 'a', 'b', 'c', 'd', 'e'], [], ['a', 'b', 'c', 'd', 'e']],
    ])('mixes recent %j and frequent %j without duplicates', (recentIds, frequentIds, expected) => {
        const entry = (id: string): { id: string; path: string; type: string; ref: string } => ({
            id,
            path: `Dashboards/${id}`,
            type: 'dashboard',
            ref: id,
        })
        expect(jumpBackObjectsForHome(recentIds.map(entry), frequentIds.map(entry), 8).map((item) => item.id)).toEqual(
            expected
        )
    })
    it('puts pinned objects first and drops them from the recent and frequent objects', () => {
        const entry = (
            id: string,
            path = `Dashboards/${id}`
        ): { id: string; path: string; type: string; ref: string } => ({
            id,
            path,
            type: 'dashboard',
            ref: id,
        })
        const tasksProduct = { id: 'product:/tasks', path: 'Tasks', type: 'task', href: '/tasks' }
        const pinned = [entry('p'), entry('b', 'Dashboards/old name'), entry('q'), tasksProduct]
        expect(
            jumpBackObjectsForHome(
                ['a', 'b', 'c'].map((id) => entry(id)),
                ['d', 'q'].map((id) => entry(id)),
                8,
                pinned
            ).map((item) => [item.id, item.jumpBackReason, item.path])
        ).toEqual([
            ['p', 'pinned', 'Dashboards/p'],
            ['b', 'pinned', 'Dashboards/b'],
            ['q', 'pinned', 'Dashboards/q'],
            ['product:/tasks', 'pinned', 'Tasks'],
            ['a', 'recent', 'Dashboards/a'],
            ['c', 'recent', 'Dashboards/c'],
            ['d', 'frequent', 'Dashboards/d'],
        ])
    })

    it('shows a pinned object with its latest recent metadata', () => {
        const pin = { id: 'x', path: 'Dashboards/Pinned name', type: 'dashboard', ref: 'x' }
        const recent = { ...pin, path: 'Dashboards/Recent name', last_viewed_at: '2026-11-19T10:00:00Z' }
        const frequent = { ...pin, path: 'Dashboards/Frequent name', last_viewed_at: '2026-11-01T10:00:00Z' }
        expect(jumpBackObjectsForHome([recent], [frequent], 8, [pin])[0]).toMatchObject({
            path: 'Dashboards/Recent name',
            last_viewed_at: '2026-11-19T10:00:00Z',
            jumpBackReason: 'pinned',
        })
    })
})
