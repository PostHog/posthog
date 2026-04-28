import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { applyDataVisualizationQueryUpdate } from './queryUpdateUtils'

describe('applyDataVisualizationQueryUpdate', () => {
    it('composes consecutive updates against the latest query state', () => {
        const queryRef = {
            current: {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT 1',
                },
                display: ChartDisplayType.Auto,
            } as DataVisualizationNode,
        }
        const updates: DataVisualizationNode[] = []

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
