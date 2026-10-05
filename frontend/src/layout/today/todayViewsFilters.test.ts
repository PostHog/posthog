import { ViewItem } from 'scenes/views/viewsUtils'

import { DEFAULT_VIEWS_FILTERS, TodayViewsFilters, filterRecentViews } from './todayViewsFilters'

const view = (id: string, overrides: Partial<ViewItem> = {}): ViewItem => ({
    type: 'notebook',
    id,
    name: id,
    href: `/notebooks/${id}`,
    timestamp: '2026-09-28T12:00:00Z',
    timestampLabel: 'Edited',
    spaceId: null,
    spaceName: null,
    createdByUuid: 'user-1',
    firstBuildTaskId: null,
    pinned: false,
    alertInvestigation: null,
    ...overrides,
})

const ITEMS = [
    view('investigation', { alertInvestigation: { alertId: 'alert-1', alertName: 'Signups' } }),
    view('notes'),
    view('pinned-dashboard', { type: 'dashboard', pinned: true }),
]

describe('todayViewsFilters', () => {
    it.each([
        ['agents keep only investigations', { madeBy: 'agents' }, ['investigation']],
        ['people leave out investigations', { madeBy: 'people' }, ['notes', 'pinned-dashboard']],
        ['pinned keeps only pinned views', { pinned: 'pinned' }, ['pinned-dashboard']],
    ] as const)('%s', (_name, narrowing, expected) => {
        const filters: TodayViewsFilters = { ...DEFAULT_VIEWS_FILTERS, ...narrowing }

        expect(filterRecentViews(ITEMS, '', filters, 'user-1').map((item) => item.id)).toEqual(expected)
    })
})
