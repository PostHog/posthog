import { dayjs } from 'lib/dayjs'

import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardTile, InsightModel } from '~/types'

import { isDueForAutomaticRefresh, minRefreshIntervalForWindow, tileWindowSeconds } from './tileRefreshInterval'

const HOUR = 3600
const DAY = 24 * HOUR

describe('tileRefreshInterval', () => {
    it.each([
        { window: 60, expected: 20 },
        { window: HOUR, expected: 20 },
        { window: HOUR + 1, expected: 60 },
        { window: 6 * HOUR, expected: 60 },
        { window: 6 * HOUR + 1, expected: 180 },
        { window: DAY, expected: 180 },
        { window: DAY + 1, expected: 900 },
        { window: 7 * DAY, expected: 900 },
        { window: 7 * DAY + 1, expected: 3600 },
        { window: Infinity, expected: 3600 },
    ])('a $window second window refreshes at most every $expected seconds', ({ window, expected }) => {
        expect(minRefreshIntervalForWindow(window, 0)).toBe(expected)
    })

    it.each([
        { name: 'a slower dashboard interval wins', window: HOUR, dashboardInterval: 900, expected: 900 },
        { name: 'a slower window wins', window: 30 * DAY, dashboardInterval: 900, expected: 3600 },
        { name: 'an unknown window keeps the dashboard interval', window: null, dashboardInterval: 15, expected: 15 },
    ])('$name', ({ window, dashboardInterval, expected }) => {
        expect(minRefreshIntervalForWindow(window, dashboardInterval)).toBe(expected)
    })

    describe('tileWindowSeconds', () => {
        const now = dayjs('2026-11-18T15:30:00Z')
        const tile = (dateRange: Record<string, any> | null, filtersOverrides?: DashboardTile['filters_overrides']) =>
            ({
                id: 1,
                insight: {
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: { kind: NodeKind.TrendsQuery, series: [], ...(dateRange ? { dateRange } : {}) },
                    },
                } as Partial<InsightModel>,
                filters_overrides: filtersOverrides,
            }) as DashboardTile

        it.each([
            { name: 'a rolling hour', dateRange: { date_from: '-1h' }, expected: HOUR },
            { name: 'last 24 hours', dateRange: { date_from: '-24h' }, expected: DAY },
            { name: 'last 7 days, without counting today so far', dateRange: { date_from: '-7d' }, expected: 7 * DAY },
            { name: 'today so far', dateRange: { date_from: 'dStart' }, expected: 15.5 * HOUR },
            {
                name: 'yesterday',
                dateRange: { date_from: '-1dStart', date_to: '-1dEnd' },
                expected: DAY - 0.001,
            },
            {
                name: 'an absolute range',
                dateRange: { date_from: '2026-11-17T00:00:00Z', date_to: '2026-11-18T00:00:00Z' },
                expected: DAY,
            },
            { name: 'all time', dateRange: { date_from: 'all' }, expected: Infinity },
            { name: 'no date range', dateRange: null, expected: null },
            { name: 'an unparseable date', dateRange: { date_from: 'soon' }, expected: null },
        ])('resolves $name', ({ dateRange, expected }) => {
            expect(tileWindowSeconds(tile(dateRange), {}, now)).toBe(expected)
        })

        it.each([
            { name: 'the dashboard date range replaces the query', overrides: undefined, expected: DAY },
            { name: 'a tile date override replaces the dashboard', overrides: { date_from: '-1h' }, expected: HOUR },
            {
                name: 'a tile ignoring dashboard filters keeps the query range',
                overrides: { ignoreDashboardFilters: true },
                expected: 7 * DAY,
            },
        ])('$name', ({ overrides, expected }) => {
            expect(tileWindowSeconds(tile({ date_from: '-7d' }, overrides), { date_from: '-24h' }, now)).toBe(expected)
        })

        it('reads a metrics query range, which has no source node', () => {
            const metricsTile = {
                id: 2,
                insight: { query: { kind: NodeKind.MetricsQuery, dateRange: { date_from: '-6h' } } },
            } as any as DashboardTile

            expect(tileWindowSeconds(metricsTile, {}, now)).toBe(6 * HOUR)
        })
    })

    describe('isDueForAutomaticRefresh', () => {
        const now = dayjs('2026-11-18T15:30:00Z')

        it.each([
            { name: 'never refreshed', ago: null, minInterval: 900, expected: true },
            { name: 'one 15 second tick after the last refresh', ago: 15, minInterval: 20, expected: false },
            { name: 'two 15 second ticks after the last refresh', ago: 30, minInterval: 20, expected: true },
            { name: 'a tick that fires slightly early', ago: 899.5, minInterval: 900, expected: true },
            { name: 'well before its minimum', ago: 600, minInterval: 900, expected: false },
        ])('$name: $expected', ({ ago, minInterval, expected }) => {
            const lastRefresh = ago === null ? null : now.subtract(ago * 1000, 'millisecond')
            expect(isDueForAutomaticRefresh(lastRefresh, minInterval, now)).toBe(expected)
        })
    })
})
