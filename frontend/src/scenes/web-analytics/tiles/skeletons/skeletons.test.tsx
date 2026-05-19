import { render } from '@testing-library/react'

import {
    AnyResponseType,
    DashboardFilter,
    DataTableNode,
    HogQLVariable,
    InsightVizNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { getAllByDataAttr, getByDataAttr, queryByDataAttr } from '~/test/byDataAttr'
import { InsightLogicProps } from '~/types'

import {
    buildDataTableTileDataNodeLogicProps,
    buildInsightVizTileDataNodeLogicProps,
    ChartTileSkeleton,
    TableTileSkeleton,
    WorldMapTileSkeleton,
} from './index'

describe('web analytics tile skeletons', () => {
    describe('data node logic prop builders', () => {
        test('preserves InsightViz data node props', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: { kind: NodeKind.TrendsQuery, series: [] },
            } as InsightVizNode
            const cachedResults = { result: [] } as unknown as AnyResponseType
            const filtersOverride = { date_from: '-24h' } as DashboardFilter
            const variablesOverride = {} as Record<string, HogQLVariable>
            const onData = jest.fn()
            const insightProps = {
                dashboardItemId: 'trend-tile',
                dataNodeCollectionId: 'web-analytics',
                doNotLoad: true,
                onData,
                loadPriority: 3,
            } as unknown as InsightLogicProps

            expect(
                buildInsightVizTileDataNodeLogicProps({
                    query,
                    insightProps,
                    cachedResults,
                    filtersOverride,
                    variablesOverride,
                    limitContext: 'posthog_ai',
                })
            ).toEqual({
                query: query.source,
                key: 'InsightViz.trend-tile',
                cachedResults,
                doNotLoad: true,
                onData,
                loadPriority: 3,
                dataNodeCollectionId: 'web-analytics',
                filtersOverride,
                variablesOverride,
                limitContext: 'posthog_ai',
            })
        })

        test('preserves DataTable data node props from query context', () => {
            const query = {
                kind: NodeKind.DataTableNode,
                source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
            } as DataTableNode
            const cachedResults = { results: [] } as unknown as AnyResponseType
            const insightProps = {
                dashboardItemId: 'table-tile',
                dataNodeCollectionId: 'web-analytics',
            } as InsightLogicProps
            const context: QueryContext = {
                insightProps,
                dataNodeLogicKey: 'custom-data-node-key',
                refresh: 'force_async',
                dataTableMaxPaginationLimit: 50,
                limitContext: 'posthog_ai',
            }

            expect(
                buildDataTableTileDataNodeLogicProps({
                    query,
                    insightProps,
                    context,
                    cachedResults,
                    uniqueKey: 'WebAnalytics.WebStatsTableTile',
                })
            ).toEqual({
                query: query.source,
                key: 'custom-data-node-key',
                cachedResults,
                dataNodeCollectionId: 'web-analytics',
                refresh: 'force_async',
                maxPaginationLimit: 50,
                limitContext: 'posthog_ai',
            })
        })
    })

    describe('TableTileSkeleton', () => {
        test('renders the default 8 body rows', () => {
            const { container } = render(<TableTileSkeleton />)
            const body = getByDataAttr(container, 'web-analytics-skeleton-table-body')
            expect(body.children.length).toBe(8)
        })

        test('honors the rows prop', () => {
            const { container } = render(<TableTileSkeleton rows={3} />)
            const body = getByDataAttr(container, 'web-analytics-skeleton-table-body')
            expect(body.children.length).toBe(3)
        })

        test('honors numericColumns prop in the header', () => {
            const { container } = render(<TableTileSkeleton numericColumns={5} />)
            const numericContainer = getByDataAttr(container, 'web-analytics-skeleton-table-header-numeric')
            expect(numericContainer.children.length).toBe(5)
        })
    })

    describe('ChartTileSkeleton', () => {
        test('renders 14 bars by default', () => {
            const { container } = render(<ChartTileSkeleton />)
            expect(getAllByDataAttr(container, 'web-analytics-skeleton-chart-bar').length).toBe(14)
        })

        test('honors the bars prop', () => {
            const { container } = render(<ChartTileSkeleton bars={6} />)
            expect(getAllByDataAttr(container, 'web-analytics-skeleton-chart-bar').length).toBe(6)
        })

        test('hides the legend strip when showLegendStrip=false', () => {
            const { container } = render(<ChartTileSkeleton showLegendStrip={false} />)
            expect(queryByDataAttr(container, 'web-analytics-skeleton-chart-legend')).toBeNull()
        })

        test('shows the legend strip by default', () => {
            const { container } = render(<ChartTileSkeleton />)
            expect(queryByDataAttr(container, 'web-analytics-skeleton-chart-legend')).not.toBeNull()
        })
    })

    test('WorldMapTileSkeleton renders its root', () => {
        const { container } = render(<WorldMapTileSkeleton />)
        expect(getByDataAttr(container, 'web-analytics-skeleton-world-map')).toBeTruthy()
    })
})
