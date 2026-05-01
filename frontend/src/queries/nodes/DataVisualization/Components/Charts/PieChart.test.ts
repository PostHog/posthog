import { getSeriesColor } from 'lib/colors'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { buildPieSlices } from './PieChart'

describe('buildPieSlices', () => {
    const xData: AxisSeries<string> = {
        column: {
            name: 'category',
            type: {
                name: 'STRING',
                isNumerical: false,
            },
            label: 'category',
            dataIndex: 0,
        },
        data: ['alpha', 'beta', 'alpha'],
    }

    it('aggregates a single y-series by x-axis label', () => {
        const yData: AxisSeries<number | null>[] = [
            {
                column: {
                    name: 'value',
                    type: {
                        name: 'INTEGER',
                        isNumerical: true,
                    },
                    label: 'value',
                    dataIndex: 1,
                },
                data: [2, 3, 5],
                settings: {},
            },
        ]

        expect(buildPieSlices(xData, yData)).toEqual([
            { label: 'alpha', value: 7, color: getSeriesColor(0) },
            { label: 'beta', value: 3, color: getSeriesColor(1) },
        ])
    })

    it('aggregates breakdown series by series total', () => {
        const yData: AxisBreakdownSeries<number | null>[] = [
            {
                name: 'first',
                data: [1, 2, null],
                settings: { display: { color: '#111111' } },
            },
            {
                name: 'second',
                data: [3, 4, 5],
                settings: { display: { color: '#222222' } },
            },
        ]

        expect(buildPieSlices(xData, yData)).toEqual([
            { label: 'first', value: 3, color: '#111111' },
            { label: 'second', value: 12, color: '#222222' },
        ])
    })

    it('falls back to one slice per y-series when there is no categorical x-axis', () => {
        const noXAxis: AxisSeries<string> = {
            column: {
                name: 'None',
                type: {
                    name: 'STRING',
                    isNumerical: false,
                },
                label: 'None',
                dataIndex: -1,
            },
            data: ['', ''],
        }

        const yData: AxisSeries<number | null>[] = [
            {
                column: {
                    name: 'apples',
                    type: {
                        name: 'INTEGER',
                        isNumerical: true,
                    },
                    label: 'apples',
                    dataIndex: 0,
                },
                data: [1, 2],
                settings: {},
            },
            {
                column: {
                    name: 'oranges',
                    type: {
                        name: 'INTEGER',
                        isNumerical: true,
                    },
                    label: 'oranges',
                    dataIndex: 1,
                },
                data: [3, 4],
                settings: {},
            },
        ]

        expect(buildPieSlices(noXAxis, yData)).toEqual([
            { label: 'apples', value: 3, color: getSeriesColor(0) },
            { label: 'oranges', value: 7, color: getSeriesColor(1) },
        ])
    })
})
