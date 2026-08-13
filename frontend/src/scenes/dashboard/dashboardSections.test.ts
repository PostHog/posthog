import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import type { DashboardTile, QueryBasedInsightModel } from '~/types'

import {
    IMPLICIT_SECTION_KEY,
    ORPHAN_SECTION_KEY,
    partitionDashboardSections,
    sectionDisplayName,
} from './dashboardSections'

const tile = (id: number, parentGroupId?: string | null): DashboardTile<QueryBasedInsightModel> => ({
    id,
    layouts: {},
    color: null,
    parent_group_id: parentGroupId,
})

const group = (
    overrides: Partial<DashboardGroupApi> & Pick<DashboardGroupApi, 'id' | 'position'>
): DashboardGroupApi => ({
    name: null,
    member_tile_ids: [],
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2026-01-01T00:00:00Z',
    last_modified_by: null,
    ...overrides,
})

describe('partitionDashboardSections', () => {
    it('returns a single implicit section when the dashboard has no groups', () => {
        const tiles = [tile(1), tile(2)]
        expect(partitionDashboardSections(tiles, [])).toEqual([
            { key: IMPLICIT_SECTION_KEY, group: null, isNamed: false, tiles },
        ])
    })

    it('keeps named empty sections and drops empty anonymous ones', () => {
        const named = group({ id: 'named', name: 'Revenue', position: 0 })
        const anonymous = group({ id: 'anon', name: null, position: 1 })
        const sections = partitionDashboardSections([], [anonymous, named])

        expect(sections.map((section) => section.key)).toEqual(['named'])
        expect(sections[0].isNamed).toBe(true)
    })

    it('orders by position then created_at and buckets tiles by parent_group_id', () => {
        const first = group({ id: 'a', name: 'A', position: 1, created_at: '2026-01-02T00:00:00Z' })
        const second = group({ id: 'b', name: 'B', position: 0, created_at: '2026-01-03T00:00:00Z' })
        const third = group({ id: 'c', name: 'C', position: 1, created_at: '2026-01-01T00:00:00Z' })
        const sections = partitionDashboardSections(
            [tile(1, 'a'), tile(2, 'c'), tile(3, 'missing'), tile(4, null)],
            [first, second, third]
        )

        expect(sections.map((section) => section.key)).toEqual(['b', 'c', 'a', ORPHAN_SECTION_KEY])
        expect(sections[1].tiles.map((item) => item.id)).toEqual([2])
        expect(sections[2].tiles.map((item) => item.id)).toEqual([1])
        expect(sections[3].tiles.map((item) => item.id)).toEqual([3, 4])
    })
})

describe('sectionDisplayName', () => {
    it.each([
        ['Revenue', 'Revenue'],
        ['  ', 'Untitled section'],
        [null, 'Untitled section'],
    ])('name=%j → %s', (name, expected) => {
        expect(sectionDisplayName(group({ id: 'g', position: 0, name }))).toBe(expected)
    })
})
