import { renderHook } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

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
