import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { responseSupportsChart } from './responseSupportsChart'

function node(
    display: ChartDisplayType,
    chartSettings?: DataVisualizationNode['chartSettings']
): DataVisualizationNode {
    return {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
        display,
        chartSettings,
    }
}

describe('responseSupportsChart', () => {
    // [name, query, responseColumns, expected]
    it.each([
        [
            'bar chart whose series are all absent (base query ran instead of compiled)',
            node(ChartDisplayType.ActionsBar, {
                xAxis: { column: 'created_at_month' },
                yAxis: [{ column: 'count_star' }],
            }),
            ['uuid', 'event', 'timestamp', 'person_mode'],
            false,
        ],
        [
            'bar chart with partial overlap (recompile kept an existing alias)',
            node(ChartDisplayType.ActionsBar, {
                xAxis: { column: 'plan' },
                yAxis: [{ column: 'count_star' }, { column: 'sum_amount' }],
            }),
            ['plan', 'count_star'],
            true,
        ],
        ['table renders whatever came back', node(ChartDisplayType.ActionsTable), ['anything', 'at', 'all'], true],
        [
            'heatmap missing its value column',
            node(ChartDisplayType.TwoDimensionalHeatmap, {
                heatmap: { yAxisColumn: 'person_mode', xAxisColumn: 'timestamp_hour', valueColumn: 'count_star' },
            }),
            ['uuid', 'event'],
            false,
        ],
        [
            'no series configured yet',
            node(ChartDisplayType.ActionsLineGraph, { xAxis: { column: 'day' } }),
            ['uuid', 'event'],
            true,
        ],
        ['no response yet', node(ChartDisplayType.ActionsBar, { yAxis: [{ column: 'count_star' }] }), undefined, true],
    ])('%s → %s', (_name, query, responseColumns, expected) => {
        expect(responseSupportsChart(query, responseColumns as string[] | undefined)).toEqual(expected)
    })
})
