import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardTile } from '~/types'

import {
    dashboardControlScopeText,
    dashboardControlsForQuery,
    getDashboardControlScopes,
    isDashboardControlHidden,
} from './dashboardControls'

const insightTile = (query: Record<string, any>): DashboardTile => ({ insight: { query } }) as unknown as DashboardTile

const trendsTile = insightTile({ kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } })
const retentionTile = insightTile({ kind: NodeKind.InsightVizNode, source: { kind: NodeKind.RetentionQuery } })
const metricsTile = insightTile({ kind: NodeKind.MetricsQuery, clauses: [] })

describe('dashboardControls', () => {
    it.each([
        ['a trends insight', trendsTile, ['dateRange', 'interval', 'properties', 'breakdown', 'testAccounts']],
        ['a retention insight', retentionTile, ['dateRange', 'properties', 'breakdown', 'testAccounts']],
        ['a metrics insight', metricsTile, ['dateRange', 'metricLabels']],
        [
            'a SQL insight',
            insightTile({ kind: NodeKind.DataVisualizationNode, source: { kind: NodeKind.HogQLQuery, query: '' } }),
            ['dateRange', 'interval', 'properties', 'breakdown', 'testAccounts'],
        ],
    ])('lists the controls of %s', (_name, tile, expected) => {
        expect(dashboardControlsForQuery(tile.insight?.query)).toEqual(expected)
    })

    it('counts the insights that each control changes', () => {
        const scopes = getDashboardControlScopes([trendsTile, retentionTile, metricsTile])

        expect(scopes.dateRange).toEqual({ applies: 3, total: 3 })
        expect(scopes.interval).toEqual({ applies: 1, total: 3 })
        expect(scopes.properties).toEqual({ applies: 2, total: 3 })
        expect(scopes.metricLabels).toEqual({ applies: 1, total: 3 })
    })

    it.each([
        [{ applies: 4, total: 9 }, 'Applies to 4 of 9 insights'],
        [{ applies: 9, total: 9 }, null],
        [{ applies: 0, total: 9 }, null],
        [{ applies: 0, total: 0 }, null],
    ])('shows scope text for %o', (scope, expected) => {
        expect(dashboardControlScopeText(scope)).toEqual(expected)
    })

    it.each([
        ['changes no insight', { applies: 0, total: 3 }, false, true],
        ['changes no insight but has a value', { applies: 0, total: 3 }, true, false],
        ['changes some insights', { applies: 1, total: 3 }, false, false],
        ['is on a dashboard with no insights', { applies: 0, total: 0 }, false, false],
    ])('hides a control that %s', (_name, scope, hasValue, expected) => {
        expect(isDashboardControlHidden(scope, hasValue)).toEqual(expected)
    })
})
