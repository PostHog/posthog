import { dayjs } from 'lib/dayjs'
import { ViewItem } from 'scenes/views/viewsUtils'

import { groupViewRows, viewRows } from './todayViewsSections'

const NOW = dayjs('2026-09-28T18:00:00Z')

const view = (id: string, timestamp: string, alertId: string | null = null): ViewItem => ({
    type: 'notebook',
    id,
    name: id,
    href: `/notebooks/${id}`,
    timestamp,
    timestampLabel: 'Edited',
    spaceId: null,
    spaceName: null,
    createdByUuid: null,
    firstBuildTaskId: null,
    pinned: false,
    alertInvestigation: alertId ? { alertId, alertName: null } : null,
})

describe('todayViewsSections', () => {
    it('stacks the investigations of one alert under its newest one, which keeps its place', () => {
        const items = [
            view('signups-3', '2026-09-28T16:00:00Z', 'signups'),
            view('notes', '2026-09-28T15:00:00Z'),
            view('signups-2', '2026-09-27T10:00:00Z', 'signups'),
            view('churn-1', '2026-09-26T10:00:00Z', 'churn'),
            view('signups-1', '2026-09-25T10:00:00Z', 'signups'),
        ]

        expect(viewRows(items, true).map((row) => `${row.item.id}×${row.count}`)).toEqual([
            'signups-3×3',
            'notes×1',
            'churn-1×1',
        ])
        expect(viewRows(items, false)).toHaveLength(5)
    })

    it.each([
        [
            'date',
            [
                ['Today', 2],
                ['Yesterday', 1],
                ['Saturday', 1],
                ['Sep 1', 1],
            ],
        ],
        ['none', [[null, 5]]],
    ] as const)('groups by %s', (grouping, expected) => {
        const rows = viewRows(
            [
                view('a', '2026-09-28T19:00:00Z'),
                view('b', '2026-09-28T09:00:00Z'),
                view('c', '2026-09-27T09:00:00Z'),
                view('d', '2026-09-26T09:00:00Z'),
                view('e', '2026-09-01T09:00:00Z'),
            ],
            true
        )

        expect(groupViewRows(rows, grouping, NOW).map((section) => [section.label, section.rows.length])).toEqual(
            expected
        )
    })
})
