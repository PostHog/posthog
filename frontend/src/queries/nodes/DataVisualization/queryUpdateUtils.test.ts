import { VisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { applyDataVisualizationQueryUpdate } from './queryUpdateUtils'

describe('applyDataVisualizationQueryUpdate', () => {
    it('keeps the BI worksheet chart type in sync with insight display edits', () => {
        const queryRef: { current: VisualizationNode } = {
            current: {
                kind: NodeKind.BIVisualizationNode,
                source: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
                config: {
                    source: null,
                    rows: [],
                    columns: [],
                    values: [],
                    filters: [],
                    limit: 1000,
                    chartType: ChartDisplayType.ActionsBar,
                },
            },
        }
        const save = jest.fn()
        applyDataVisualizationQueryUpdate(
            queryRef,
            (query) => ({ ...query, display: ChartDisplayType.ActionsLineGraph }),
            save
        )
        expect(save).toHaveBeenCalledWith(
            expect.objectContaining({
                kind: NodeKind.BIVisualizationNode,
                config: expect.objectContaining({ chartType: ChartDisplayType.ActionsLineGraph }),
                source: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
            })
        )
    })

    it('composes consecutive updates against the latest query state', () => {
        const queryRef = {
            current: {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT 1',
                },
                display: ChartDisplayType.Auto,
            } as VisualizationNode,
        }
        const updates: VisualizationNode[] = []

        applyDataVisualizationQueryUpdate(
            queryRef,
            (query) => ({
                ...query,
                display: ChartDisplayType.TwoDimensionalHeatmap,
            }),
            (query) => updates.push(query)
        )

        applyDataVisualizationQueryUpdate(
            queryRef,
            (query) => ({
                ...query,
                chartSettings: {
                    ...query.chartSettings,
                    heatmap: {
                        ...query.chartSettings?.heatmap,
                        xAxisColumn: 'screen_width',
                    },
                },
            }),
            (query) => updates.push(query)
        )

        expect(updates).toHaveLength(2)
        expect(updates[1].display).toBe(ChartDisplayType.TwoDimensionalHeatmap)
        expect(updates[1].chartSettings?.heatmap?.xAxisColumn).toBe('screen_width')
    })
})
