import { renderHook } from '@testing-library/react'

import { ResultCustomizationBy } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import type { SqlChartProps } from './SqlChart'
import { buildBarValueChartConfig } from './sqlLineGraphAdapter'
import { useSqlChartModel } from './useSqlChartModel'

it('keeps off-scale reference lines when horizontal bars have a partial shared domain', () => {
    initKeaTests()
    const { result } = renderHook(() =>
        useSqlChartModel(
            {
                visualizationType: ChartDisplayType.ActionsBarValue,
                chartSettings: {},
                xData: {
                    column: {
                        name: 'category',
                        type: { name: 'STRING', isNumerical: false },
                        label: 'Category',
                        dataIndex: 0,
                    },
                    data: ['A', 'B'],
                },
                yData: [
                    {
                        column: {
                            name: 'count',
                            type: { name: 'INTEGER', isNumerical: true },
                            label: 'Count',
                            dataIndex: 1,
                        },
                        data: [10, 20],
                        settings: {},
                    },
                ],
                goalLines: [{ label: 'Target', value: 200, displayIfCrossed: true }],
                valueDomain: { min: 0, include: [100] },
            },
            buildBarValueChartConfig
        )
    )
    expect(result.current?.config.bars?.valueDomain).toEqual({ min: 0, include: [200, 100] })
})

it.each([ChartDisplayType.ActionsBar, ChartDisplayType.ActionsBarValue])(
    'colors categories without splitting the series in %s',
    (visualizationType) => {
        initKeaTests()
        const props = {
            visualizationType,
            chartSettings: {
                colorBarsByCategory: true as boolean,
                resultCustomizations: {
                    B: { customColor: '#123456', assignmentBy: ResultCustomizationBy.Value as const },
                },
            },
            xData: {
                column: {
                    name: 'category',
                    type: { name: 'STRING', isNumerical: false },
                    label: 'Category',
                    dataIndex: 0,
                },
                data: ['A', 'B', 'A'],
            },
            yData: [
                {
                    column: {
                        name: 'count',
                        type: { name: 'INTEGER', isNumerical: true },
                        label: 'Count',
                        dataIndex: 1,
                    },
                    data: [10, 20, 30],
                    settings: {},
                },
            ],
        } satisfies SqlChartProps
        const { result, rerender } = renderHook(
            ({ chartSettings, yData }) =>
                useSqlChartModel({ ...props, chartSettings, yData }, buildBarValueChartConfig),
            { initialProps: { chartSettings: props.chartSettings, yData: props.yData } }
        )
        expect(result.current?.series).toHaveLength(1)
        const bars = result.current?.series[0].bars
        expect(bars).toHaveLength(3)
        expect(bars?.[0].color).toBe(result.current?.theme.colors[0])
        expect(bars?.[1].color).toBe('#123456')
        expect(bars?.[2].color).toBe(bars?.[0].color)
        expect(result.current?.series[0].data).toEqual([10, 20, 30])
        rerender({ chartSettings: { ...props.chartSettings, colorBarsByCategory: false }, yData: props.yData })
        expect(result.current?.series[0].bars).toBeUndefined()
        rerender({
            chartSettings: props.chartSettings,
            yData: [...props.yData, { ...props.yData[0], data: [40, 50, 60] }],
        })
        expect(result.current?.series).toHaveLength(2)
        expect(result.current?.series.every((series) => series.bars === undefined)).toBe(true)
    }
)
