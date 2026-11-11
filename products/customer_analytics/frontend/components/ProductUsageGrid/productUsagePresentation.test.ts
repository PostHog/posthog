import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import {
    getProductUsageChannelCounts,
    getProductUsageChannelLabel,
    getProductUsageFirstSeries,
    getProductUsageGrouping,
    getProductUsagePathShares,
    getProductUsagePersonSummary,
} from '../ProductActivity/productUsagePresentation'

describe('productUsagePresentation', () => {
    it('preserves the canonical role rows and includes products without a role', () => {
        const { series, groups, columnsPerGroup } = getProductUsageGrouping(
            BOOK_ACTIVITY_MATRIX_MOCK.series,
            BOOK_ACTIVITY_MATRIX_MOCK.groupings,
            'role'
        )
        expect(columnsPerGroup).toBe(6)
        expect(groups.map(({ items }) => items?.length)).toEqual([6, 6, 6, 3])
        expect(new Set(groups.flatMap(({ items }) => items))).toHaveProperty('size', 21)
        expect(series.filter(({ group }) => group === 'product_cs').map(({ color }) => color)).toEqual(
            Array(6).fill(groups[0].color)
        )
    })

    it('keeps products in every use case and assigns each product its own color', () => {
        const { series, groups, columnsPerGroup } = getProductUsageGrouping(
            BOOK_ACTIVITY_MATRIX_MOCK.series,
            BOOK_ACTIVITY_MATRIX_MOCK.groupings,
            'usecase'
        )
        expect(columnsPerGroup).toBe(5)
        expect(groups.filter(({ items }) => items?.includes('replay'))).toHaveLength(2)
        expect(new Set(series.map(({ color }) => color)).size).toBe(series.length)
    })

    it.each(['day', 'week', 'month'] as const)('puts first use in its %s bucket only', (interval) => {
        const firstUse = [
            { row: 'one', series: 'a', date: '2026-11-02' },
            { row: 'one', series: 'old', date: '2026-11-01' },
            { row: 'two', series: 'other', date: '2026-11-02' },
        ]
        expect(getProductUsageFirstSeries(firstUse, 'one', '2026-11-02', interval)).toEqual(['a'])
    })

    it.each([
        ['both channels', { users: 3, uiUsers: 2, agentUsers: 2 }, '2 people in the app, 2 people through AI agents'],
        ['agents only', { users: 1, uiUsers: 0, agentUsers: 1 }, '0 people in the app, 1 person through AI agents'],
        ['the app only', { users: 2, uiUsers: 2, agentUsers: 0 }, null],
        ['an older response without channel counts', { users: 4 }, null],
        ['no cell', null, null],
    ])('labels the channel split for %s', (_, cell, expected) => {
        const data = cell ? [{ row: 'account', column: '2026-11-02', series: 'pa', ...cell }] : []
        expect(getProductUsageChannelLabel(getProductUsageChannelCounts(data, 'account', '2026-11-02', 'pa'))).toBe(
            expected
        )
    })

    it.each([
        ['page time and actions', { engagedSeconds: 90, actionCount: 1 }, '90s · 1 action'],
        ['agent calls only', { engagedSeconds: 0, actionCount: 0, agentCalls: 4 }, '4 agent calls'],
        ['everything', { engagedSeconds: 30, actionCount: 2, agentCalls: 1 }, '30s · 2 actions · 1 agent call'],
        ['nothing', { engagedSeconds: 0, actionCount: 0 }, '0s · 0 actions'],
    ])('summarises a person with %s', (_, person, expected) => {
        expect(getProductUsagePersonSummary(person, (seconds) => `${seconds}s`)).toBe(expected)
    })

    it('sizes page bars against the longest page and survives an empty list', () => {
        expect(
            getProductUsagePathShares([
                { path: '/a', seconds: 300 },
                { path: '/b', seconds: 75 },
            ]).map(({ share }) => share)
        ).toEqual([1, 0.25])
        expect(getProductUsagePathShares([])).toEqual([])
    })
})
