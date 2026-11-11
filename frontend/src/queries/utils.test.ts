import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { DataTableNode, DataVisualizationNode, Node, NodeKind } from '~/queries/schema/schema-general'
import type { InsightQueryNode } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    convertDataTableNodeToDataVisualizationNode,
    dataWarehouseSourcesFromResponse,
    getShowLegend,
    isMetricInsightQuery,
    supportsBarValueStacking,
    taxonomicSessionFilterToHogQL,
} from './utils'

describe('taxonomicSessionFilterToHogQL', () => {
    it('maps session properties to the session prefix', () => {
        expect(taxonomicSessionFilterToHogQL(TaxonomicFilterGroupType.SessionProperties, '$entry_current_url')).toEqual(
            'session.$entry_current_url'
        )
    })

    it('maps person properties to person.properties', () => {
        expect(taxonomicSessionFilterToHogQL(TaxonomicFilterGroupType.PersonProperties, '$browser')).toEqual(
            'person.properties.$browser'
        )
    })

    it('passes SQL expressions through', () => {
        expect(taxonomicSessionFilterToHogQL(TaxonomicFilterGroupType.HogQLExpression, 'count()')).toEqual('count()')
    })

    it('rejects event-scoped picks, which the sessions table cannot resolve', () => {
        expect(taxonomicSessionFilterToHogQL(TaxonomicFilterGroupType.EventProperties, '$browser')).toBeNull()
        expect(taxonomicSessionFilterToHogQL(TaxonomicFilterGroupType.EventFeatureFlags, '$feature/foo')).toBeNull()
    })
})

describe('convertDataTableNodeToDataVisualizationNode', () => {
    it('preserves visible and pinned columns from legacy HogQL data table nodes', () => {
        const convertedNode = convertDataTableNodeToDataVisualizationNode({
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events',
            },
            columns: ['event', 'timestamp', 'person_id'],
            hiddenColumns: ['person_id'],
            pinnedColumns: ['event', 'person_id'],
        } as DataTableNode)

        expect(convertedNode).toEqual({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events',
            },
            display: ChartDisplayType.ActionsTable,
            tableSettings: {
                columns: [{ column: 'event' }, { column: 'timestamp' }],
                pinnedColumns: ['event'],
            },
        } as DataVisualizationNode)
    })

    it('preserves additional legacy table config when converting HogQL data table nodes', () => {
        const convertedNode = convertDataTableNodeToDataVisualizationNode({
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events limit 10',
            },
            full: true,
            embedded: true,
            showReload: true,
            columns: ['event'],
        } as DataTableNode)

        expect(convertedNode).toEqual({
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from events limit 10',
            },
            display: ChartDisplayType.ActionsTable,
            full: true,
            embedded: true,
            showReload: true,
            tableSettings: {
                columns: [{ column: 'event' }],
            },
        })
    })
})

describe('getShowLegend', () => {
    const trends = (display: ChartDisplayType, showLegend?: boolean): InsightQueryNode => ({
        kind: NodeKind.TrendsQuery,
        series: [],
        trendsFilter: { display, showLegend },
    })

    it.each([
        ['a proportion bar with few parts', trends(ChartDisplayType.ActionsProportionBar), 5, true],
        ['a proportion bar with many parts', trends(ChartDisplayType.ActionsProportionBar), 25, undefined],
        ['a proportion bar before its parts load', trends(ChartDisplayType.ActionsProportionBar), undefined, undefined],
        ['a proportion bar with the legend turned off', trends(ChartDisplayType.ActionsProportionBar, false), 5, false],
        ['a line chart', trends(ChartDisplayType.ActionsLineGraph), 5, undefined],
    ])('%s', (_name, query, partCount, expected) => {
        expect(getShowLegend(query, partCount)).toBe(expected)
    })
})

describe('supportsBarValueStacking', () => {
    const breakdown = { breakdown: '$browser', breakdown_type: 'event' as const }
    const trends = (display: ChartDisplayType, withBreakdown: boolean): InsightQueryNode =>
        ({
            kind: NodeKind.TrendsQuery,
            series: [],
            trendsFilter: { display },
            ...(withBreakdown ? { breakdownFilter: breakdown } : {}),
        }) as InsightQueryNode

    it.each([
        {
            name: 'trends + bar-value + breakdown',
            query: trends(ChartDisplayType.ActionsBarValue, true),
            expected: true,
        },
        {
            name: 'trends + bar-value without breakdown',
            query: trends(ChartDisplayType.ActionsBarValue, false),
            expected: false,
        },
        {
            name: 'trends + vertical bar + breakdown',
            query: trends(ChartDisplayType.ActionsBar, true),
            expected: false,
        },
        {
            name: 'trends + line + breakdown',
            query: trends(ChartDisplayType.ActionsLineGraph, true),
            expected: false,
        },
        {
            name: 'funnels + breakdown',
            query: { kind: NodeKind.FunnelsQuery, series: [], breakdownFilter: breakdown } as InsightQueryNode,
            expected: false,
        },
        { name: 'null query', query: null, expected: false },
    ])('returns $expected for $name', ({ query, expected }) => {
        expect(supportsBarValueStacking(query)).toBe(expected)
    })
})

describe('dataWarehouseSourcesFromResponse', () => {
    it('extracts sources from a response that has them', () => {
        expect(
            dataWarehouseSourcesFromResponse({
                results: [],
                used_data_warehouse_sources: [{ id: 'src-1', source_type: 'Stripe', table_name: 'stripe.charges' }],
            })
        ).toEqual([{ id: 'src-1', source_type: 'Stripe', table_name: 'stripe.charges' }])
    })

    it('returns an empty array when the field is absent or the response is not an object', () => {
        expect(dataWarehouseSourcesFromResponse({ results: [] })).toEqual([])
        expect(dataWarehouseSourcesFromResponse(null)).toEqual([])
        expect(dataWarehouseSourcesFromResponse(undefined)).toEqual([])
    })
})

describe('isMetricInsightQuery', () => {
    it.each([
        [
            'SQL metric',
            {
                kind: NodeKind.DataVisualizationNode,
                source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
                display: ChartDisplayType.Metric,
            },
            true,
        ],
        [
            'trends metric',
            {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                    trendsFilter: { display: ChartDisplayType.Metric },
                },
            },
            true,
        ],
        [
            'SQL line chart',
            {
                kind: NodeKind.DataVisualizationNode,
                source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
                display: ChartDisplayType.ActionsLineGraph,
            },
            false,
        ],
    ])('identifies a %s', (_label, query, expected) => {
        expect(isMetricInsightQuery(query as Node)).toBe(expected)
    })
})
