import { DashboardType, QueryBasedInsightModel } from '~/types'

import { getDashboardAutoRefreshRestriction, getLast7DaysDashboardFilters } from './dashboardAutoRefresh'

function dashboardWithRange(dateFrom: string): DashboardType<QueryBasedInsightModel> {
    return {
        id: 1,
        name: 'Dashboard',
        filters: { date_from: dateFrom },
        tiles: [
            {
                id: 1,
                color: null,
                insight: {
                    id: 2,
                    name: 'Trend',
                    query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery' } },
                },
            },
        ],
    } as unknown as DashboardType<QueryBasedInsightModel>
}

describe('dashboard auto-refresh eligibility', () => {
    it.each([
        ['-30d', null],
        ['-31d', 'dashboard'],
        ['-1dStart', null],
        ['invalid-date-range', 'dashboard'],
    ])('handles dashboard range %s', (dateFrom, expectedSource) => {
        expect(getDashboardAutoRefreshRestriction(dashboardWithRange(dateFrom), 'UTC')?.source ?? null).toBe(
            expectedSource
        )
    })

    it('identifies the insight whose effective range is too long', () => {
        const dashboard = {
            ...dashboardWithRange('-7d'),
            filters: {},
            tiles: [
                {
                    id: 1,
                    color: null,
                    insight: {
                        id: 2,
                        name: 'Long-running trend',
                        query: {
                            kind: 'InsightVizNode',
                            source: { kind: 'TrendsQuery', dateRange: { date_from: '-90d' } },
                        },
                    },
                },
            ],
        } as unknown as DashboardType<QueryBasedInsightModel>

        expect(getDashboardAutoRefreshRestriction(dashboard, 'UTC')).toEqual({
            source: 'insight',
            insightName: 'Long-running trend',
        })
    })

    it('uses persisted dashboard filters instead of temporary overrides', () => {
        const dashboard = {
            ...dashboardWithRange('-7d'),
            persisted_filters: { date_from: '-90d' },
        }

        expect(getDashboardAutoRefreshRestriction(dashboard, 'UTC')?.source).toBe('dashboard')
    })

    it('does not use temporary overrides when persisted filters are null', () => {
        const dashboard = {
            ...dashboardWithRange('-90d'),
            persisted_filters: null,
        }

        expect(getDashboardAutoRefreshRestriction(dashboard, 'UTC')).toBeNull()
    })

    it('disables auto refresh when the dashboard range is long even with a short tile override', () => {
        const dashboard = dashboardWithRange('-90d')
        dashboard.tiles[0].filters_overrides = { date_from: '-7d' }

        expect(getDashboardAutoRefreshRestriction(dashboard, 'UTC')?.source).toBe('dashboard')
    })

    it('sets the dashboard date range to the last 7 days without removing other filters', () => {
        const dashboard = {
            ...dashboardWithRange('-90d'),
            persisted_filters: { date_from: '-90d', properties: [{ key: '$browser', value: 'Chrome' }] },
        }

        expect(getLast7DaysDashboardFilters(dashboard)).toEqual({
            date_from: '-7d',
            date_to: null,
            explicitDate: false,
            properties: [{ key: '$browser', value: 'Chrome' }],
        })
    })
})
