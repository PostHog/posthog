import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { ChartDisplayType } from '~/types'

import {
    BIEditorView,
    buildBIQuery,
    DEFAULT_BI_CONFIG,
    mergeBIChartSettings,
    parseBIEditorState,
} from './biEditorTypes'
import { mergeBITableSettings } from './biMeasureSettings'

const field: BIField = {
    id: 'amount',
    name: 'amount',
    expression: 'amount',
    type: 'float',
    source: { table: 'orders' },
}
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: field.source,
    chartType: ChartDisplayType.ActionsBar,
    rows: [
        {
            ...field,
            id: 'created_at',
            name: 'created_at',
            expression: 'created_at',
            type: 'datetime',
            dateBucket: 'day',
        },
    ],
    values: [
        {
            field,
            aggregation: 'sum',
            formatting: { prefix: '$', style: 'number', decimalPlaces: 2 },
            display: { label: 'Revenue', displayType: 'bar', yAxisPosition: 'left' },
        },
        {
            field,
            aggregation: 'average',
            formatting: { style: 'short' },
            display: { label: 'Average order', displayType: 'line', yAxisPosition: 'right' },
        },
    ],
}

describe('BI measure display', () => {
    it.each([ChartDisplayType.ActionsBar, ChartDisplayType.TwoDimensionalHeatmap])(
        'persists independent formats and axes for %s',
        (chartType) => {
            const parsed = parseBIEditorState(BIEditorView.BI, JSON.stringify({ ...config, chartType }))!.config
            expect(parsed.values).toEqual(config.values)
            const node = buildBIQuery(parsed)!.node
            if (chartType === ChartDisplayType.ActionsBar) {
                expect(node.chartSettings?.xAxis?.column).toBe('toStartOfDay(created_at)')
            }
            expect(node.chartSettings?.yAxis?.map((axis) => axis.settings)).toEqual(
                config.values.map((value) => ({ formatting: value.formatting, display: value.display }))
            )
            expect(node.tableSettings?.columns?.map((column) => column.column)).toEqual([
                chartType === ChartDisplayType.TwoDimensionalHeatmap ? 'bi_row_created_at' : 'toStartOfDay(created_at)',
                'sum_amount',
                'average_amount_2',
            ])
            const merged = mergeBITableSettings(
                {
                    pinnedColumns: ['date'],
                    columns: [{ column: 'sum_amount', settings: { formatting: { prefix: 'old' } } }],
                },
                node.tableSettings
            )
            expect(merged?.pinnedColumns).toEqual(['date'])
            expect(
                merged?.columns?.find((column) => column.column === 'sum_amount')?.settings?.formatting?.prefix
            ).toBe('$')
            const labeled = mergeBIChartSettings(node.chartSettings, {
                yAxis: [{ column: 'average_amount_2', settings: { display: { label: 'Updated label' } } }],
            })
            expect(labeled?.yAxis?.[0].settings?.display).toEqual({
                label: 'Updated label',
                displayType: 'line',
                yAxisPosition: 'right',
            })
        }
    )

    it.each([
        { formatting: { decimalPlaces: -1 } },
        { formatting: { style: 'currency' } },
        { display: { yAxisPosition: 'top' } },
    ])('rejects invalid persisted display settings %j', (settings) => {
        expect(
            parseBIEditorState(BIEditorView.BI, { ...config, values: [{ ...config.values[0], ...settings }] })
        ).toBeNull()
    })
})
