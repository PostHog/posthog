import { useActions, useValues } from 'kea'

import { IconGraph, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

function ChartFilterOptionLabel(props: { label: string; description?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-[2px]">
            <span>{props.label}</span>
            <span className="text-xs text-tertiary font-normal">{props.description}</span>
        </div>
    )
}

const OPTIONS: LemonSelectOptions<ChartDisplayType> = [
    {
        title: 'Time series',
        options: [
            {
                value: ChartDisplayType.ActionsLineGraph,
                icon: <IconTrends />,
                label: 'Line chart',
                labelInMenu: (
                    <ChartFilterOptionLabel
                        label="Line chart"
                        description="Retention over time plotted as a continuous line for each cohort."
                    />
                ),
            },
            {
                value: ChartDisplayType.ActionsBar,
                icon: <IconGraph />,
                label: 'Bar chart',
                labelInMenu: (
                    <ChartFilterOptionLabel
                        label="Bar chart"
                        description="Retention over time as vertical bars for each cohort."
                    />
                ),
            },
        ],
    },
]

export function RetentionChartPicker(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSelect
            key="2"
            value={retentionFilter?.display || ChartDisplayType.ActionsLineGraph}
            onChange={(value) => {
                updateInsightFilter({ display: value })
            }}
            dropdownPlacement="bottom-end"
            optionTooltipPlacement="left"
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            options={OPTIONS}
            size="small"
            disabledReason={editingDisabledReason}
        />
    )
}
