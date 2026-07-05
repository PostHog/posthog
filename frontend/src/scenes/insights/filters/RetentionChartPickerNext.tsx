import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconGraph, IconTrends } from '@posthog/icons'
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

interface RetentionChartOption {
    value: ChartDisplayType
    icon: ReactNode
    label: string
    description: string
}

const OPTIONS: RetentionChartOption[] = [
    {
        value: ChartDisplayType.ActionsLineGraph,
        icon: <IconTrends />,
        label: 'Line chart',
        description: 'Retention over time plotted as a continuous line for each cohort.',
    },
    {
        value: ChartDisplayType.ActionsBar,
        icon: <IconGraph />,
        label: 'Bar chart',
        description: 'Retention over time as vertical bars for each cohort.',
    },
]

const ITEMS = Object.fromEntries(
    OPTIONS.map((option) => [
        option.value,
        <span className="flex items-center gap-2" key={option.value}>
            {option.icon}
            {option.label}
        </span>,
    ])
)

export function RetentionChartPickerNext(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <Select
            value={retentionFilter?.display || ChartDisplayType.ActionsLineGraph}
            items={ITEMS}
            onValueChange={(value: string | null) => {
                if (value) {
                    updateInsightFilter({ display: value as ChartDisplayType })
                }
            }}
            disabled={!!editingDisabledReason}
        >
            <SelectTrigger size="sm" data-quill data-attr="chart-filter" title={editingDisabledReason ?? undefined}>
                <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" alignItemWithTrigger={false}>
                <SelectGroup>
                    <SelectGroupLabel>Time series</SelectGroupLabel>
                    {OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.icon}
                            <span className="flex flex-col">
                                <span>{option.label}</span>
                                <span className="text-xs font-normal whitespace-normal text-muted-foreground">
                                    {option.description}
                                </span>
                            </span>
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
