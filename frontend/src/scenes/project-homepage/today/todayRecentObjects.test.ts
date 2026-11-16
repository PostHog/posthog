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
        expect(
            jumpBackObjectsForHome(recentIds.map(entry), frequentIds.map(entry), 8, null).map((item) => item.id)
        ).toEqual(expected)
    })

    it.each([
        { case: 'no recents', recentIds: [], frequentIds: [], expected: ['primary:home'] },
        {
            case: 'a recent copy of it',
            recentIds: ['a', 'home', 'b'],
            frequentIds: [],
            expected: ['primary:home', 'recent:a', 'recent:b'],
        },
        {
            case: 'a frequent copy of it',
            recentIds: ['a', 'b', 'c'],
            frequentIds: ['home', 'd'],
            expected: ['primary:home', 'recent:a', 'recent:b', 'frequent:d'],
        },
        {
            case: 'more items than the limit',
            recentIds: ['a', 'b', 'c', 'd', 'e'],
            frequentIds: [],
            expected: ['primary:home', 'recent:a', 'recent:b', 'recent:c'],
        },
    ])('puts the primary dashboard first, once, with $case', ({ recentIds, frequentIds, expected }) => {
        const entry = (id: string): { id: string; path: string; type: string; ref: string } => ({
            id,
            path: `Dashboards/${id}`,
            type: 'dashboard',
            ref: id,
        })
        expect(
            jumpBackObjectsForHome(recentIds.map(entry), frequentIds.map(entry), 4, entry('home')).map(
                (item) => `${item.jumpBackReason}:${item.id}`
            )
        ).toEqual(expected)
    })
})
