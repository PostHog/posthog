import { router } from 'kea-router'

import { DataTableNode, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { insightOnDashboard, tileFromInsight } from '~/scenes/dashboard/dashboardLogic.testHelpers'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyGroupFilter, PropertyOperator } from '~/types'

import { dashboardResultFilterLogic } from './dashboardResultFilterLogic'
import {
    DashboardResultSelection,
    getDashboardResultActors,
    getDashboardResultTargets,
    readDashboardResultFilter,
} from './dashboardResultFilters'

const query: InsightVizNode<TrendsQuery> = {
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
}
const selection: DashboardResultSelection = {
    dashboardId: 1,
    tileId: 1,
    label: 'Paid users',
    query: {
        kind: NodeKind.ActorsQuery,
        source: {
            kind: NodeKind.InsightActorsQuery,
            source: query.source,
            day: '2026-01-02',
            breakdown: "Paid user's plan",
        },
    },
}

describe('dashboard result population filters', () => {
    it('preserves OR groups and skips the source, opted-out tiles, and SQL', () => {
        const properties: PropertyGroupFilter = {
            type: FilterLogicalOperator.Or,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: 'plan',
                            value: 'paid',
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            ],
        }
        const target: InsightVizNode<TrendsQuery> = { ...query, source: { ...query.source, properties } }
        const tiles = [1, 2, 3].map((id) => tileFromInsight({ ...insightOnDashboard(id, [1]), query: target }, id))
        tiles[2].filters_overrides = { ignoreDashboardFilters: true }
        const sqlQuery: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
        }
        tiles.push(
            tileFromInsight(
                {
                    ...insightOnDashboard(4, [1]),
                    query: sqlQuery,
                },
                4
            )
        )
        const targets = getDashboardResultTargets(tiles, selection)
        expect(Object.keys(targets)).toEqual(['2'])
        expect(targets[2].source.properties).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                properties,
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        expect.objectContaining({
                            type: PropertyFilterType.HogQL,
                            key: expect.stringContaining('matchesInsight('),
                        }),
                    ],
                },
            ],
        })
        const request = getDashboardResultActors({
            title: '',
            query: {
                kind: NodeKind.InsightActorsQuery,
                source: { ...targets[2].source, dateRange: undefined },
                day: '2026-01-02',
            },
        })
        expect(JSON.stringify(request)).not.toContain('matchesInsight(')
        expect(request?.source).toMatchObject({ source: { properties } })
        expect(readDashboardResultFilter(JSON.stringify({ ...selection, query: request }))?.query).toEqual(request)
        expect(target.source.properties).toEqual(properties)
    })

    it('restores after tiles load, replaces a selection, toggles it off, and clears with the URL', () => {
        initKeaTests()
        router.actions.push(
            '/project/1/dashboard/1',
            {},
            { insight_filter: JSON.stringify(selection), other: 'preserved' }
        )
        const logic = dashboardResultFilterLogic({ dashboardId: 1, tiles: [] })
        const unmount = logic.mount()
        try {
            expect(logic.values.selection).toBeNull()
            const tiles = [1, 2].map((id) => tileFromInsight({ ...insightOnDashboard(id, [1]), query }, id))
            dashboardResultFilterLogic({ dashboardId: 1, tiles })
            expect(logic.values.selection).toEqual(selection)
            expect(Object.keys(logic.values.targets)).toEqual(['2'])
            const next = {
                ...selection,
                query: { ...selection.query, source: { ...selection.query.source!, day: '2026-01-03' } },
            } as DashboardResultSelection
            logic.actions.selectResult(next)
            expect(logic.values.selection).toEqual(next)
            logic.actions.selectResult(next)
            expect(logic.values.selection).toBeNull()
            expect(router.values.currentLocation.hashParams.insight_filter).toBeUndefined()
            expect(router.values.currentLocation.hashParams.other).toBe('preserved')
            logic.actions.selectResult(selection)
            router.actions.push(
                '/project/1/dashboard/1',
                {},
                { bi_filter: JSON.stringify({ dashboardId: 1, tileId: 3, record: {} }) }
            )
            expect(logic.values.selection).toBeNull()
            logic.actions.selectResult(selection)
            expect(router.values.currentLocation.hashParams.bi_filter).toBeUndefined()
            expect(logic.values.selection).toEqual(selection)
            router.actions.push('/project/1/dashboard/1')
            expect(logic.values.selection).toBeNull()
        } finally {
            unmount()
            window.history.replaceState({}, '', '/')
        }
    })

    it.each([
        'null',
        'bad json',
        JSON.stringify({
            ...selection,
            query: { kind: NodeKind.ActorsQuery, source: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' } },
        }),
    ])('rejects unsupported filter links: %s', (value) => {
        expect(readDashboardResultFilter(value)).toBeNull()
    })
})
