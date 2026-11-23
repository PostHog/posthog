import { FileSystemEntry } from '~/queries/schema/schema-general'

import { TodayRecent, TodayViewedRecent } from './todayRecents'
import { todayRecentsMenuItems } from './todayRecentsMenu'

const entry = (overrides: Partial<FileSystemEntry>): FileSystemEntry => ({
    id: overrides.ref ?? 'id',
    path: 'Unfiled/Item',
    ...overrides,
})

describe('todayRecentsMenuItems', () => {
    test.each<[string, FileSystemEntry[], TodayViewedRecent<TodayRecent>[], [string, string, string | null][]]>([
        [
            'merges every list, newest first, with untimed recents last',
            [entry({ type: 'insight', ref: 'abc', path: 'Unfiled/Signups', last_viewed_at: '2026-01-02T00:00:00Z' })],
            [
                { type: 'person', name: 'Ada', href: '/person/1' },
                {
                    type: 'error_tracking_issue',
                    name: 'Timeout',
                    href: '/error-tracking/9',
                    viewedAt: Date.parse('2026-01-03T00:00:00Z'),
                },
            ],
            [
                ['Timeout', 'issue', '2026-01-03T00:00:00.000Z'],
                ['Signups', 'insight', '2026-01-02T00:00:00Z'],
                ['Ada', 'person', null],
            ],
        ],
        [
            'shows a page in two lists once, with its latest visit',
            [
                entry({
                    type: 'cohort',
                    ref: '5',
                    path: 'Unfiled/Churned',
                    href: '/project/1/cohorts/5',
                    last_viewed_at: '2026-01-01T00:00:00Z',
                }),
            ],
            [
                {
                    type: 'cohort',
                    name: 'Churned users',
                    href: '/cohorts/5',
                    viewedAt: Date.parse('2026-01-05T00:00:00Z'),
                },
            ],
            [['Churned users', 'cohort', '2026-01-05T00:00:00.000Z']],
        ],
        [
            'leaves out a file system row whose href leaves the app',
            [
                entry({
                    type: 'dashboard',
                    ref: '1',
                    href: 'https://example.com/login',
                    last_viewed_at: '2026-01-02T00:00:00Z',
                }),
                entry({ type: 'dashboard', ref: '2', href: '//example.com', last_viewed_at: '2026-01-02T00:00:00Z' }),
                entry({
                    type: 'dashboard',
                    ref: '3',
                    path: 'Unfiled/Revenue',
                    href: '/dashboard/3',
                    last_viewed_at: '2026-01-01T00:00:00Z',
                }),
            ],
            [],
            [['Revenue', 'dashboard', '2026-01-01T00:00:00Z']],
        ],
        [
            'leaves out tasks and the unnamed file system releases',
            [
                entry({ type: 'task', ref: 't1', href: '/tasks/t1', last_viewed_at: '2026-01-01T00:00:00Z' }),
                entry({ type: 'release', ref: 'r1', href: '/releases/r1', last_viewed_at: '2026-01-04T00:00:00Z' }),
            ],
            [
                {
                    type: 'release',
                    id: 'r1',
                    name: 'Launch',
                    href: '/releases/r1',
                    viewedAt: Date.parse('2026-01-02T00:00:00Z'),
                },
            ],
            [['Launch', 'release', '2026-01-02T00:00:00.000Z']],
        ],
    ])('%s', (_, fileSystemRecents, localRecents, expected) => {
        expect(
            todayRecentsMenuItems(fileSystemRecents, localRecents).map(({ name, typeLabel, viewedAt }) => [
                name,
                typeLabel,
                viewedAt,
            ])
        ).toEqual(expected)
    })
})
