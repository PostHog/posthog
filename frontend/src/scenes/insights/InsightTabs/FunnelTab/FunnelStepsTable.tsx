import React from 'react'
import { useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonTable, LemonTableColumnGroup } from 'lib/components/LemonTable'
import { FlattenedFunnelStep } from '~/types'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getSeriesColor } from 'scenes/funnels/funnelUtils'
import { getActionFilterFromFunnelStep } from './funnelStepTableUtils'

export function FunnelStepsTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { insightLoading, steps, flattenedSteps } = useValues(logic)

    const columnsGrouped = [
        {
            children: [
                {
                    title: 'Breakdown',
                    dataIndex: 'breakdown_value',
                },
            ],
        },
        ...steps.map((step) => ({
            title: <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />,
            children: [
                {
                    title: 'Completed',
                    dataIndex: `count`,
                },
                {
                    title: 'Rate',
                    dataIndex: 'conversionRate',
                },
            ],
        })),
    ] as LemonTableColumnGroup<FlattenedFunnelStep>[]

    return (
        <LemonTable
            dataSource={flattenedSteps}
            columns={columnsGrouped}
            loading={insightLoading}
            rowRibbonColor={(series) => getSeriesColor(series?.breakdownIndex, flattenedSteps.length === 1)}
        />
    )
}
