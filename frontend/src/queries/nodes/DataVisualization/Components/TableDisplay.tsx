import { useActions, useValues } from 'kea'

import { IconGraph, IconLifecycle, IconPieChart, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOptions, LemonSelectProps } from '@posthog/lemon-ui'

import { Icon123, IconAreaChart, IconCumulativeChart, IconTableChart } from 'lib/lemon-ui/icons'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

interface TableDisplayProps extends Pick<LemonSelectProps<ChartDisplayType>, 'disabledReason'> {}

export const TableDisplay = ({ disabledReason }: TableDisplayProps): JSX.Element => {
    const { setVisualizationType } = useActions(dataVisualizationLogic)
    const { visualizationType } = useValues(dataVisualizationLogic)

    const options: LemonSelectOptions<ChartDisplayType> = [
        {
            title: 'Table',
            options: [
                {
                    value: ChartDisplayType.ActionsTable,
                    icon: <IconTableChart />,
                    label: 'Table',
                },
                {
                    value: ChartDisplayType.BoldNumber,
                    icon: <Icon123 />,
                    label: 'Number',
                },
            ],
        },
        {
            title: 'Time series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraph,
                    icon: <IconTrends />,
                    label: 'Line chart',
                },
                {
                    value: ChartDisplayType.ActionsAreaGraph,
                    icon: <IconAreaChart />,
                    label: 'Area chart',
                },
                {
                    value: ChartDisplayType.ActionsUnstackedBar,
                    icon: <IconGraph />,
                    label: 'Bar chart',
                },
                {
                    value: ChartDisplayType.ActionsStackedBar,
                    icon: <IconLifecycle />,
                    label: 'Stacked bar chart',
                },
            ],
        },
        {
            title: 'Cumulative time series',
            options: [
                {
                    value: ChartDisplayType.ActionsLineGraphCumulative,
                    icon: <IconCumulativeChart />,
                    label: 'Line chart (cumulative)',
                },
            ],
        },
        {
            title: 'Total value',
            options: [
                {
                    value: ChartDisplayType.ActionsPie,
                    icon: <IconPieChart />,
                    label: 'Pie chart',
                },
                {
                    value: ChartDisplayType.ActionsBarValue,
                    icon: <IconGraph className="rotate-90" />,
                    label: 'Bar chart',
                },
            ],
        },
    ]

    return (
        <LemonSelect
            disabledReason={disabledReason}
            value={visualizationType}
            onChange={(value) => {
                setVisualizationType(value)
            }}
            dropdownPlacement="bottom-end"
            optionTooltipPlacement="left"
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            options={options}
        />
    )
}
